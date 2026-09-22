"""Optimized TSP Solver: Uses Nearest Neighbor heuristic + 2-Opt local search."""

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

def nearest_neighbor():
    unvisited = set(range(1, len(CITIES)))
    tour = [0]
    curr = 0
    while unvisited:
        nxt = min(unvisited, key=lambda city: distance(CITIES[curr], CITIES[city]))
        tour.append(nxt)
        unvisited.remove(nxt)
        curr = nxt
    return tour

def two_opt(tour):
    best_tour = list(tour)
    best_dist = calculate_tour_distance(best_tour)
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best_tour) - 1):
            for j in range(i + 1, len(best_tour)):
                if j - i == 1:
                    continue
                new_tour = best_tour[:i] + best_tour[i:j][::-1] + best_tour[j:]
                new_dist = calculate_tour_distance(new_tour)
                if new_dist < best_dist - 1e-4:
                    best_tour = new_tour
                    best_dist = new_dist
                    improved = True
                    break
            if improved:
                break
    return best_tour, best_dist

def main():
    initial_tour = nearest_neighbor()
    optimized_tour, total_dist = two_opt(initial_tour)
    
    output = {
        "status": "PASS",
        "total_distance": round(total_dist, 2),
        "score": round(total_dist, 2),
        "tour_length": len(optimized_tour),
        "algorithm": "nearest_neighbor_with_2opt"
    }
    print(json.dumps(output))

if __name__ == "__main__":
    main()
