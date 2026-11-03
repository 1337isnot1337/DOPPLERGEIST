"""Process-local resource measurements."""
import resource
import sys


def process_peak_rss_kib():
    """Return process peak RSS in KiB; do not include child processes.

    Linux getrusage may retain a larger high-water mark from a pre-exec
    parent. Its VmHWM reports the post-exec address space instead. Other
    systems fall back to their getrusage semantics.
    """
    try:
        with open('/proc/self/status', encoding='ascii') as status:
            for line in status:
                if line.startswith('VmHWM:'):
                    fields = line.split()
                    if len(fields) == 3 and fields[2] == 'kB':
                        return int(fields[1])
    except (OSError, ValueError):
        pass
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1024 if sys.platform == 'darwin' else peak
