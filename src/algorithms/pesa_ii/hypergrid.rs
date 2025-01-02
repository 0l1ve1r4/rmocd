//! algorithms/pesa_ii/hypergrid.rs
//! This Source Code Form is subject to the terms of The GNU General Public License v3.0
//! Copyright 2024 - Guilherme Santos. If a copy of the MPL was not distributed with this
//! file, You can obtain one at https://www.gnu.org/licenses/gpl-3.0.h

use crate::graph::Partition;
use rayon::prelude::*;
use std::cmp::Ordering;

pub const GRID_DIVISIONS: usize = 8;
#[allow(dead_code)]
pub const MAX_ARCHIVE_SIZE: usize = 1000;

#[derive(Clone, Debug)]
pub struct Solution {
    pub partition: Partition,
    pub objectives: Vec<f64>,
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct HyperBox {
    pub solutions: Vec<Solution>,
    pub coordinates: Vec<usize>,
}

impl HyperBox {
    #[allow(dead_code)]
    pub fn density(&self) -> f64 {
        self.solutions.len() as f64
    }
}

impl Solution {
    pub fn dominates(&self, other: &Solution) -> bool {
        let mut has_better = false;
        for (self_obj, other_obj) in self.objectives.iter().zip(other.objectives.iter()) {
            if self_obj < other_obj {
                return false;
            }
            if self_obj > other_obj {
                has_better = true;
            }
        }
        has_better
    }
}

#[allow(dead_code)]
pub fn truncate_archive(archive: &mut Vec<Solution>, max_size: usize) {
    if archive.len() <= max_size {
        return;
    }

    // Create hyperboxes
    let hyperboxes = create(archive, GRID_DIVISIONS);

    // Calculate crowding distances within each hyperbox
    let mut solution_scores: Vec<(usize, f64)> = archive
        .iter()
        .enumerate()
        .map(|(index, solution)| {
            let hyperbox = hyperboxes
                .iter()
                .find(|hb| {
                    hb.solutions
                        .iter()
                        .any(|s| s.objectives == solution.objectives)
                })
                .unwrap();

            // Calculate crowding distance within hyperbox
            let crowding_distance = calculate_crowding_distance(solution, &hyperbox.solutions);

            // Combined score: higher density is worse, higher crowding distance is better
            let score = hyperbox.density() / (crowding_distance + 1.0);
            (index, score)
        })
        .collect();

    // Sort by score (higher score means more likely to be removed)
    solution_scores.sort_by(|a, b| {
        b.1.partial_cmp(&a.1)
            .unwrap_or(Ordering::Equal)
            .then_with(|| a.0.cmp(&b.0))
    });

    // Remove solutions
    let indices_to_remove: Vec<usize> = solution_scores
        .iter()
        .take(archive.len() - max_size)
        .map(|(index, _)| *index)
        .collect();

    let mut indices_to_remove = indices_to_remove;
    indices_to_remove.sort_unstable_by(|a, b| b.cmp(a));

    for index in indices_to_remove {
        archive.remove(index);
    }
}

/// Calculates crowding distance for a solution within its neighborhood
fn calculate_crowding_distance(solution: &Solution, neighbors: &[Solution]) -> f64 {
    if neighbors.len() <= 1 {
        return f64::INFINITY;
    }

    let num_objectives = solution.objectives.len();
    let mut distance = 0.0;

    for obj_index in 0..num_objectives {
        // Sort neighbors by this objective
        let mut sorted_neighbors: Vec<&Solution> = neighbors.iter().collect();
        sorted_neighbors.sort_by(|a, b| {
            a.objectives[obj_index]
                .partial_cmp(&b.objectives[obj_index])
                .unwrap_or(Ordering::Equal)
        });

        // Find the nearest neighbors
        if let Some(pos) = sorted_neighbors
            .iter()
            .position(|s| s.objectives == solution.objectives)
        {
            if pos > 0 && pos < sorted_neighbors.len() - 1 {
                let diff = (sorted_neighbors[pos + 1].objectives[obj_index]
                    - sorted_neighbors[pos - 1].objectives[obj_index])
                    .abs();
                distance += diff;
            }
        }
    }

    distance / num_objectives as f64
}

pub fn create(solutions: &[Solution], divisions: usize) -> Vec<HyperBox> {
    if solutions.is_empty() {
        return Vec::new();
    }

    // Calculate min/max values in parallel
    let obj_len = solutions[0].objectives.len();
    let (min_values, max_values) = rayon::join(
        || {
            (0..obj_len)
                .into_par_iter()
                .map(|i| {
                    solutions
                        .par_iter()
                        .map(|s| s.objectives[i])
                        .min_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
                        .unwrap()
                })
                .collect::<Vec<_>>()
        },
        || {
            (0..obj_len)
                .into_par_iter()
                .map(|i| {
                    solutions
                        .par_iter()
                        .map(|s| s.objectives[i])
                        .max_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
                        .unwrap()
                })
                .collect::<Vec<_>>()
        },
    );

    // Use a concurrent HashMap for grouping solutions
    use dashmap::DashMap;
    let hyperbox_map = DashMap::new();

    solutions.par_iter().for_each(|solution| {
        let coordinates = solution
            .objectives
            .iter()
            .enumerate()
            .map(|(i, &obj)| {
                let normalized = if (max_values[i] - min_values[i]).abs() < f64::EPSILON {
                    0.0
                } else {
                    (obj - min_values[i]) / (max_values[i] - min_values[i])
                };
                (normalized * divisions as f64).min((divisions - 1) as f64) as usize
            })
            .collect::<Vec<_>>();

        hyperbox_map
            .entry(coordinates.clone())
            .and_modify(|solutions: &mut Vec<Solution>| solutions.push(solution.clone()))
            .or_insert_with(|| vec![solution.clone()]);
    });

    // Convert DashMap to Vec<HyperBox>
    hyperbox_map
        .into_iter()
        .map(|(coordinates, solutions)| HyperBox {
            solutions,
            coordinates,
        })
        .collect()
}

/// Parallel version of select_from_hypergrid
pub fn select<'a>(hyperboxes: &'a [HyperBox], rng: &mut impl rand::Rng) -> &'a Solution {
    // Compute total weight in parallel
    let total_weight: f64 = hyperboxes
        .par_iter()
        .map(|hb| 1.0 / (hb.solutions.len() as f64))
        .sum();

    let mut random_value = rng.gen::<f64>() * total_weight;

    // Selection remains sequential to handle the cumulative weights
    for hyperbox in hyperboxes {
        let weight = if hyperbox.solutions.is_empty() {
            0.0
        } else {
            1.0 / (hyperbox.solutions.len() as f64)
        };
        if random_value <= weight {
            // Randomly select a solution from the chosen hyperbox
            return &hyperbox.solutions[rng.gen_range(0..hyperbox.solutions.len())];
        }
        random_value -= weight;
    }

    // Fallback to last hyperbox
    let last_box = hyperboxes.last().unwrap();
    &last_box.solutions[rng.gen_range(0..last_box.solutions.len())]
}