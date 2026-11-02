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
        self.origin = self.time[0]
        self.relative_time = self.time - self.origin
        v = self.velocity
        if v is None:
            v = np.gradient(self.xyz, self.relative_time, axis=0)
        self.spline = CubicHermiteSpline(self.relative_time, self.xyz, v, extrapolate=False)
        self.derivative = self.spline.derivative()

    def position(self, t):
        return self.spline(np.asarray(t) - self.origin)

    def speed_vector(self, t):
        return self.derivative(np.asarray(t) - self.origin)

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
                raise ValueError("Acoustic model requires a subsonic source")
            correction = (tau - t + distance / c) / derivative
            tau = np.clip(tau - correction, start, end)
            if np.max(np.abs(correction)) < 1e-7:
                break
        delta = self.position(tau) - observer
        distance = np.linalg.norm(delta, axis=-1)
        radial = np.sum(delta * self.speed_vector(tau), axis=-1) / distance
        factor = c / (c + radial)
        return tuple(np.where(supported, a, np.nan) for a in (factor, tau, distance))

    def closest_approaches(self, observer, max_distance=np.inf, c=343.0, step=2.0):
        """All interior local 3-D minima, including repeated passes by one flight."""
        sample = np.unique(np.r_[np.arange(self.time[0], self.time[-1], step), self.time[-1]])
        range2 = np.sum((self.position(sample) - observer) ** 2, axis=-1)
        indices = find_peaks(-range2)[0]
        events = []
        for i in indices:
            # Optimize relative time: scipy's absolute-time stopping term
            # is too loose when Unix timestamps are around 1.8 billion seconds.
            mid = sample[i]
            result = minimize_scalar(lambda dt: np.sum((self.position(mid + dt) - observer) ** 2),
                                     bounds=(sample[i - 1] - mid, sample[i + 1] - mid),
                                     method="bounded", options={"xatol": 0.001})
            t = mid + result.x
            distance = np.sqrt(result.fun)
            if distance <= max_distance:
                events.append({"flight_id": self.id, "emission_time": float(t),
                               "receive_time": float(t + distance / c),
                               "distance_m": float(distance),
                               "speed_mps": float(np.linalg.norm(self.speed_vector(t)))})
        return events


def straight_doppler(t_receive, f0, speed, slant, cpa_receive, c=343.0):
    """Exact retarded-time solution for a constant-speed straight flyover."""
    # Relative emission t=0 is geometric CPA; its sound arrives at slant/c.
    u = np.asarray(t_receive) - cpa_receive + slant / c
    beta = speed / c
    tau = (u - np.sqrt((beta * u) ** 2 + (1 - beta ** 2) * (slant / c) ** 2)) / (1 - beta ** 2)
    radial = speed ** 2 * tau / np.sqrt(slant ** 2 + (speed * tau) ** 2)
    return f0 * c / (c + radial)
