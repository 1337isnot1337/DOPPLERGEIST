"""3-D geometry and emission-time acoustic propagation, in SI units.

Range rate is positive for a receding source. Observer and aircraft heights must
use the same vertical datum. ECEF treats those heights as ellipsoidal; supplying
orthometric heights to both is a documented common-datum approximation.
"""
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import CubicHermiteSpline
from scipy.optimize import minimize_scalar
from scipy.signal import find_peaks


class AcousticSupportError(ValueError):
    """A trajectory cannot support the assumed emission-time acoustic model."""
    def __init__(self, track_id, reason, *, emission_intervals_s=None, receive_intervals_s=None):
        self.track_id, self.reason = track_id, reason
        self.emission_intervals_s = emission_intervals_s
        self.receive_intervals_s = receive_intervals_s
        super().__init__(f"{track_id}: {reason}")


def ecef(lat, lon, height):
    lat, lon, height = np.broadcast_arrays(np.deg2rad(lat), np.deg2rad(lon), height)
    a, e2 = 6378137.0, 6.6943799901413165e-3
    n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    return np.stack(((n + height) * np.cos(lat) * np.cos(lon),
                     (n + height) * np.cos(lat) * np.sin(lon),
                     (n * (1 - e2) + height) * np.sin(lat)), axis=-1)


def velocity_ecef(lat, lon, east, north, up):
    lat, lon = np.deg2rad(lat), np.deg2rad(lon)
    return np.stack((-np.sin(lon) * east - np.sin(lat) * np.cos(lon) * north + np.cos(lat) * np.cos(lon) * up,
                     np.cos(lon) * east - np.sin(lat) * np.sin(lon) * north + np.cos(lat) * np.sin(lon) * up,
                     np.cos(lat) * north + np.sin(lat) * up), axis=-1)


@dataclass
class Track:
    id: str
    time: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    altitude: np.ndarray
    typecode: str = ""
    velocity: np.ndarray | None = None

    def __post_init__(self):
        self.time, self.lat, self.lon, self.altitude = [np.asarray(a, dtype=float) for a in
            (self.time, self.lat, self.lon, self.altitude)]
        if len(self.time) < 3 or not np.all(np.diff(self.time) > 0):
            raise ValueError(f"{self.id}: need >=3 strictly ordered unique timestamps")
        if not np.all(np.isfinite(np.column_stack((self.time, self.lat, self.lon, self.altitude)))):
            raise ValueError(f"{self.id}: nonfinite track data")
        self.xyz = ecef(self.lat, self.lon, self.altitude)
        self._xyz_min = self.xyz.min(axis=0)
        self._xyz_max = self.xyz.max(axis=0)
        self._max_sample_gap = float(np.max(np.diff(self.time)))
        self.origin = self.time[0]
        self.relative_time = self.time - self.origin
        v = self.velocity
        if v is None:
            v = np.gradient(self.xyz, self.relative_time, axis=0)
        self.spline = CubicHermiteSpline(self.relative_time, self.xyz, v, extrapolate=False)
        self.derivative = self.spline.derivative()
        # The derivative's quadratic Bezier control vectors bound its speed.
        # Most clean intervals need no polynomial roots; exact maxima are cached
        # only when this inexpensive upper bound reaches the requested c.
        v = np.asarray(v)
        middle = 3*np.diff(self.xyz, axis=0)/np.diff(self.time)[:, None]-v[:-1]-v[1:]
        self._speed_upper = np.maximum.reduce([np.linalg.norm(a, axis=1)
            for a in (v[:-1], middle, v[1:])])
        self._speed_peak = np.full(len(self.time)-1, np.nan)

    def position(self, t):
        return self.spline(np.asarray(t) - self.origin)

    def speed_vector(self, t):
        return self.derivative(np.asarray(t) - self.origin)

    def _unsupported_motion_intervals(self, c):
        """Find non-subsonic native spline intervals, caching speed extrema.

        Velocity is quadratic in normalized interval time. Its squared norm is
        quartic, so endpoints and real roots of its cubic derivative enumerate
        all extrema (in double precision). A small margin treats the sonic
        boundary as unsupported.
        """
        limit = c*(1-1e-10)
        suspicious = np.flatnonzero(self._speed_upper >= limit)
        for i in suspicious:
            dt = self.time[i+1]-self.time[i]
            if np.isnan(self._speed_peak[i]):
                a, b, d = self.derivative.c[:, i]
                a, b = a*dt**2, b*dt
                stationary = [2*np.dot(b, d), 2*(np.dot(b, b)+2*np.dot(a, d)),
                              6*np.dot(a, b), 4*np.dot(a, a)]
                roots = np.polynomial.polynomial.polyroots(stationary)
                samples = [0., 1.] + [float(r.real) for r in roots
                    if abs(r.imag) <= 1e-8 and 0 < r.real < 1]
                self._speed_peak[i] = max(np.linalg.norm((a*u+b)*u+d) for u in samples)
        return suspicious[self._speed_peak[suspicious] >= limit]

    def validate_motion_support(self, c=343.0):
        """Require subsonic motion throughout the source used for CPA proposals.

        The outer search may isolate this track and retain incomplete coverage.
        Direct ridge scoring instead tests the time-local arrival envelope below.
        """
        indices = self._unsupported_motion_intervals(c)
        if len(indices):
            raise AcousticSupportError(self.id, "non_subsonic_motion",
                emission_intervals_s=[[float(self.time[i]), float(self.time[i+1])] for i in indices])

    def outside_observer_radius(self, observers, radius, c=343.0):
        """Prove all observers are beyond a validated track's range.

        Every instant lies at most half a native sample interval from one
        endpoint. Subsonic speed therefore bounds each ECEF component's
        displacement from an observed position by c * max_gap / 2. An axis
        separation larger than the radius proves the entire cubic trajectory
        and its sampled polyline cannot enter any observer's search sphere.
        """
        self.validate_motion_support(c)
        if not np.isfinite(radius):
            return False
        scale = max(1.0, float(np.max(np.abs(self._xyz_min))),
                    float(np.max(np.abs(self._xyz_max))), abs(radius), abs(c * self._max_sample_gap))
        rounding = 64 * np.finfo(float).eps * scale
        margin = c * self._max_sample_gap / 2 + rounding
        lower = self._xyz_min - margin - radius - rounding
        upper = self._xyz_max + margin + radius + rounding
        return bool(np.all(np.any((observers < lower) | (observers > upper), axis=-1)))

    def _check_motion_support(self, receive_time, observer, c):
        """Reject possible arrivals from unsupported native emission intervals.

        Bezier position boxes conservatively enclose affected arrival times,
        without assuming monotonic propagation in an unsupported interval.
        """
        emissions, arrivals = [], []
        for i in self._unsupported_motion_intervals(c):
            dt = self.time[i+1]-self.time[i]
            p0, p1 = self.xyz[i:i+2]
            v0, v1 = self.speed_vector(self.time[i:i+2])
            controls = np.array([p0, p0+dt*v0/3, p1-dt*v1/3, p1])
            lo, hi = controls.min(axis=0), controls.max(axis=0)
            nearest = np.maximum(np.maximum(lo-observer, observer-hi), 0)
            farthest = np.maximum(np.abs(lo-observer), np.abs(hi-observer))
            arrival_lo = self.time[i]+np.linalg.norm(nearest)/c
            arrival_hi = self.time[i+1]+np.linalg.norm(farthest)/c
            # Enlarge for Unix-epoch rounding rather than excluding an endpoint.
            tolerance = max(1e-7, 4*abs(np.spacing(max(abs(arrival_lo), abs(arrival_hi)))))
            if np.any((receive_time >= arrival_lo-tolerance) & (receive_time <= arrival_hi+tolerance)):
                emissions.append([float(self.time[i]), float(self.time[i+1])])
                arrivals.append([float(arrival_lo-tolerance), float(arrival_hi+tolerance)])
        if emissions:
            raise AcousticSupportError(self.id, "non_subsonic_motion",
                emission_intervals_s=emissions, receive_intervals_s=arrivals)

    def acoustic(self, receive_time, observer, c=343.0):
        """Return Doppler factor, emission time and range at receiver-clock times.

        Solve t_receive = t_emit + |x(t_emit)-observer|/c with Newton's method.
        Values outside the supported emission interval are NaN, never extrapolated.
        """
        t = np.asarray(receive_time, dtype=float)
        start, end = self.time[[0, -1]]
        arrival_start = start + np.linalg.norm(self.xyz[0] - observer) / c
        arrival_end = end + np.linalg.norm(self.xyz[-1] - observer) / c
        supported = (t >= arrival_start) & (t <= arrival_end)
        initial = self.position(np.clip(t, start, end))
        tau = np.clip(t - np.linalg.norm(initial - observer, axis=-1) / c, start, end)
        for _ in range(10):
            delta = self.position(tau) - observer
            distance = np.linalg.norm(delta, axis=-1)
            radial = np.sum(delta * self.speed_vector(tau), axis=-1) / distance
            derivative = 1 + radial / c
            if np.any(derivative <= 0):
                raise AcousticSupportError(self.id, "non_monotone_arrival")
            correction = (tau - t + distance / c) / derivative
            updated = np.clip(tau - correction, start, end)
            unchanged = np.array_equal(tau, updated)
            tau = updated
            # A fixed point at Unix-epoch precision would repeat identically
            # even when its unrounded correction exceeds the tolerance.
            if np.max(np.abs(correction)) < 1e-7 or unchanged:
                break
        delta = self.position(tau) - observer
        distance = np.linalg.norm(delta, axis=-1)
        radial = np.sum(delta * self.speed_vector(tau), axis=-1) / distance
        factor = c / (c + radial)
        self._check_motion_support(t, observer, c)
        arrival_derivative = 1+radial/c
        if np.any(arrival_derivative <= 0):
            raise AcousticSupportError(self.id, "non_monotone_arrival")
        remaining_correction = (tau-t+distance/c)/arrival_derivative
        tolerance = np.maximum(1e-7, 4*np.abs(np.spacing(t)))
        if np.any(supported & (~np.isfinite(remaining_correction) | (np.abs(remaining_correction) > tolerance))):
            raise AcousticSupportError(self.id, "emission_solver_not_converged")
        return tuple(np.where(supported, a, np.nan) for a in (factor, tau, distance))

    def closest_approaches(self, observer, max_distance=np.inf, c=343.0, step=2.0):
        """All interior local 3-D minima, including repeated passes by one flight."""
        self.validate_motion_support(c)
        sample = np.unique(np.r_[np.arange(self.time[0], self.time[-1], step), self.time[-1]])
        range2 = np.sum((self.position(sample) - observer) ** 2, axis=-1)
        indices = find_peaks(-range2)[0]
        brackets = [(sample[i-1], sample[i], sample[i+1]) for i in indices]
        # find_peaks excludes the first and last sample. An interior minimum
        # can nevertheless lie between an endpoint and its neighbour, while
        # the endpoint is the smallest sampled range. Check the range-rate
        # signs before optimizing those intervals; an endpoint itself is not
        # evidence of a complete passage.
        edges = []
        if range2[0] <= range2[1]:
            edges.append((sample[0], sample[1]))
        if range2[-1] <= range2[-2] and (len(sample) > 2 or not edges):
            edges.append((sample[-2], sample[-1]))
        for lo, hi in edges:
            t = np.array([lo, hi])
            radial = np.sum((self.position(t) - observer) * self.speed_vector(t), axis=-1)
            if radial[0] < 0 < radial[1]:
                brackets.append((lo, lo, hi))
        events = []
        for lo, mid, hi in brackets:
            # Optimize relative time: scipy's absolute-time stopping term
            # is too loose when Unix timestamps are around 1.8 billion seconds.
            result = minimize_scalar(lambda dt: np.sum((self.position(mid + dt) - observer) ** 2),
                                     bounds=(lo - mid, hi - mid),
                                     method="bounded", options={"xatol": 0.001})
            t = mid + result.x
            distance = np.sqrt(result.fun)
            if distance <= max_distance:
                events.append({"flight_id": self.id, "emission_time": float(t),
                               "receive_time": float(t + distance / c),
                               "distance_m": float(distance),
                               "speed_mps": float(np.linalg.norm(self.speed_vector(t)))})
        return sorted(events, key=lambda event: event["emission_time"])


def straight_doppler(t_receive, f0, speed, slant, cpa_receive, c=343.0):
    """Exact retarded-time solution for a constant-speed straight flyover."""
    # Relative emission t=0 is geometric CPA; its sound arrives at slant/c.
    u = np.asarray(t_receive) - cpa_receive + slant / c
    beta = speed / c
    tau = (u - np.sqrt((beta * u) ** 2 + (1 - beta ** 2) * (slant / c) ** 2)) / (1 - beta ** 2)
    radial = speed ** 2 * tau / np.sqrt(slant ** 2 + (speed * tau) ** 2)
    return f0 * c / (c + radial)
