"""Naive Baseline TSP Solver: Visits cities in raw index order (0 -> 1 -> 2 ... -> 24 -> 0)."""

import json
import math

CITIES = [
    (60, 200), (180, 200), (80, 180), (140, 180), (20, 160),
    (100, 160), (200, 160), (140, 140), (40, 120), (100, 120),
    (180, 100), (60, 80), (120, 80), (180, 60), (20, 40),
    (100, 40), (200, 40), (20, 20), (60, 20), (160, 20),
    (30, 110), (90, 70), (150, 130), (70, 170), (130, 30)
]

def distance(c1, c2):
    return math.hypot(c1[0] - c2[0], c1[1] - c2[1])

def calculate_tour_distance(tour):
    total = 0.0
    for i in range(len(tour)):
        total += distance(CITIES[tour[i]], CITIES[tour[(i + 1) % len(tour)]])
    return total

def main():
    # Naive baseline: simple sequential order
    tour = list(range(len(CITIES)))
    total_dist = calculate_tour_distance(tour)
    
    # Emit standardized objective output
    output = {
        "status": "PASS",
        "total_distance": round(total_dist, 2),
        "score": round(total_dist, 2),
        "tour_length": len(tour),
        "algorithm": "naive_sequential"
    }
    print(json.dumps(output))

if __name__ == "__main__":
    main()
