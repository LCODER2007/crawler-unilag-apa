"""
Lightweight geo helpers — great-circle arc generation for the collaboration
map. Plain spherical interpolation (slerp); no shapely/pyproj dependency.
"""

import math
from typing import List


def great_circle_arc(
    lat1: float, lon1: float, lat2: float, lon2: float, n_points: int = 32
) -> List[List[float]]:
    """Interpolate a great-circle path between two points.

    Returns [[lon, lat], ...] (GeoJSON coordinate order) with n_points
    vertices inclusive of both endpoints."""
    phi1, lam1 = math.radians(lat1), math.radians(lon1)
    phi2, lam2 = math.radians(lat2), math.radians(lon2)

    # Cartesian unit vectors
    a = (
        math.cos(phi1) * math.cos(lam1),
        math.cos(phi1) * math.sin(lam1),
        math.sin(phi1),
    )
    b = (
        math.cos(phi2) * math.cos(lam2),
        math.cos(phi2) * math.sin(lam2),
        math.sin(phi2),
    )

    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    omega = math.acos(dot)
    if omega < 1e-9:  # coincident points
        return [[lon1, lat1], [lon2, lat2]]

    sin_omega = math.sin(omega)
    coords = []
    for i in range(n_points):
        t = i / (n_points - 1)
        s1 = math.sin((1 - t) * omega) / sin_omega
        s2 = math.sin(t * omega) / sin_omega
        x = s1 * a[0] + s2 * b[0]
        y = s1 * a[1] + s2 * b[1]
        z = s1 * a[2] + s2 * b[2]
        coords.append(
            [
                round(math.degrees(math.atan2(y, x)), 4),
                round(math.degrees(math.atan2(z, math.hypot(x, y))), 4),
            ]
        )
    return coords
