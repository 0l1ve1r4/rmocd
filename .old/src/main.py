import utils
import random
import plots as pl
import pandas as pd
import networkx as nx
import genetic_algorithm as ga

"""
1. 10 runs variar o mu 0.1 - 0.9
    - calcular a media do nmi par a par das 10 execuções para cada algoritmo
    - plot grafico de linha com intervalo de confiança y - nmi media, x - mu
    
aumentar mu 

"""

from collections import defaultdict
from cdlib import algorithms, evaluation, NodeClustering
from networkx.generators.community import LFR_benchmark_graph

NUM_GENERATIONS = 400
POPULATION_SIZE = 100


def compute_nmi(partition_ga, partition_louvain, graph):
    # Convert GA partition to CDLIB NodeClustering format
    communities_ga = defaultdict(list)
    for node, community in partition_ga.items():
        communities_ga[community].append(node)
    ga_communities_list = [community for community in communities_ga.values()]
    ga_node_clustering = NodeClustering(ga_communities_list, graph, "Genetic Algorithm")

    nmi_value = evaluation.normalized_mutual_information(
        ga_node_clustering, partition_louvain
    )
    return nmi_value.score


data = []

def convert_edgelist_to_graph(edgelist_file):
    """Convert an edgelist to a NetworkX graph."""
    G = nx.read_edgelist(edgelist_file, delimiter=',', nodetype=int)
    return G

def calculate_objectives(graph, partition) -> (float, float, float):
    total_edges = graph.number_of_edges()
    if total_edges == 0:
        return 0.0, 0.0, 0.0

    intra_sum = 0.0
    inter = 0.0
    total_edges_doubled = 2.0 * total_edges

    communities = defaultdict(set)
    for node, community in partition.items():
        communities[community].add(node)

    for community_nodes in communities.values():
        community_edges = 0
        community_degree = 0.0

        for node in community_nodes:
            node_degree = len(list(graph.neighbors(node)))
            community_degree += node_degree

            for neighbor in graph.neighbors(node):
                if neighbor in community_nodes:
                    community_edges += 1

        if not graph.is_directed():
            community_edges /= 2

        intra_sum += community_edges
        normalized_degree = community_degree / total_edges_doubled
        inter += normalized_degree ** 2

    intra = 1.0 - (intra_sum / total_edges)
    modularity = 1.0 - intra - inter
    modularity = max(-1.0, min(1.0, modularity))

    return modularity, intra, inter

# Generate initial population
def generate_initial_population(graph, population_size):
    population = []
    nodes = list(graph.nodes())
    for _ in range(population_size):
        partition = {node: random.randint(0, len(nodes)-1) for node in nodes}
        population.append(partition)
    return population

# Two-point crossover
def crossover(parent1, parent2):
    keys = list(parent1.keys())
    idx1, idx2 = sorted(random.sample(range(len(keys)), 2))
    child = parent1.copy()
    for i in range(idx1, idx2):
        child[keys[i]] = parent2[keys[i]]
    return child

# Mutation ensuring mutations only between adjacent nodes
def mutate(partition, graph):
    node = random.choice(list(partition.keys()))
    neighbors = list(graph.neighbors(node))
    if neighbors:
        partition[node] = partition[random.choice(neighbors)]
    return partition

# Selection based on Pareto dominance 
def selection(population, fitnesses):
    # Sort based on modularity
    sorted_population = [p for _, p in sorted(zip(fitnesses, population), key=lambda x: x[0][0], reverse=True)]
    return sorted_population[:len(population)//2]

# Calculate the distance between two solutions
def calculate_distance(fitness1, fitness2):
    intra_diff = fitness1[1] - fitness2[1]
    inter_diff = fitness1[2] - fitness2[2]
    distance = math.sqrt(intra_diff ** 2 + inter_diff ** 2)
    return distance

# Genetic algorithm 
def genetic_algorithm(graph, generations=80, population_size=100):
    best_fitness_history = []
    avg_fitness_history = []
    
    real_population = generate_initial_population(graph, population_size)
    for generation in range(generations):
        print(f"Geracao: {generation}" )

        with Pool() as pool:
            args = [(graph, partition) for partition in real_population]
            fitnesses = pool.starmap(calculate_objectives, args)

        modularity_values = [fitness[0] for fitness in fitnesses]
        best_fitness = max(modularity_values)
        avg_fitness = sum(modularity_values) / len(modularity_values)
        best_fitness_history.append(best_fitness)
        avg_fitness_history.append(avg_fitness)

        # Select individuals for mating
        real_population = selection(real_population, fitnesses)

        # Generate new population
        new_population = []
        while len(new_population) < population_size:
            parents = random.sample(real_population, 2)
            child = crossover(parents[0], parents[1])
            child = mutate(child, graph)
            new_population.append(child)
        real_population = new_population

    # Final evaluation for real network
    real_fitnesses = [calculate_objectives(graph, partition) for partition in real_population]
    real_pareto_front = [partition for fitness, partition in zip(real_fitnesses, real_population) if fitness[0] == max(real_fitnesses, key=lambda x: x[0])[0]]

    # Run on random network
    random_graph = nx.gnm_random_graph(graph.number_of_nodes(), graph.number_of_edges())
    random_population = generate_initial_population(random_graph, population_size)
    for generation in range(generations):
        # Evaluate fitness
        fitnesses = [calculate_objectives(random_graph, partition) for partition in random_population]
        # Select individuals for mating
        random_population = selection(random_population, fitnesses)
        # Generate new population
        new_population = []
        while len(new_population) < population_size:
            parents = random.sample(random_population, 2)
            child = crossover(parents[0], parents[1])
            child = mutate(child, random_graph)
            new_population.append(child)
        random_population = new_population

    # Final evaluation for random network
    random_fitnesses = [calculate_objectives(random_graph, partition) for partition in random_population]
    random_pareto_front_fitnesses = [fitness for fitness in random_fitnesses if fitness[0] == max(random_fitnesses, key=lambda x: x[0])[0]]

    # Max-Min Distance Selection
    max_deviation = -1
    best_partition = None
    deviations = []
    for real_partition, real_fitness in zip(real_pareto_front, real_fitnesses):
        # Calculate deviation of this solution
        min_distance = min([calculate_distance(real_fitness, random_fitness) for random_fitness in random_pareto_front_fitnesses])
        deviations.append((real_partition, real_fitness, min_distance))
        if min_distance > max_deviation:
            max_deviation = min_distance
            best_partition = real_partition
            best_fitness = real_fitness

    return best_partition, deviations, real_fitnesses, random_fitnesses, best_fitness_history, avg_fitness_history

if __name__ == "__main__":
    for i in range(1, 2):
        try:
            try:
                G = convert_edgelist_to_graph("/home/ol1ve1r4/Desktop/mocd/src/graphs/artificials/karate.edgelist")
                
            except Exception as e:
                print(f"Failed to generate graph at iteration {i}: {e}")
                continue

            # Louvain Algorithm
            louvain_communities = algorithms.louvain(G)

            # Ga Visualization - Run the genetic algorithm with Max-Min Distance selection
            (
                best_partition,
                deviations,
                real_fitnesses,
                random_fitnesses,
                best_history,
                avg_history,
            ) = ga.genetic_algorithm(G, NUM_GENERATIONS, POPULATION_SIZE)

            # Visualize GA x Louvain
            nmi_score = compute_nmi(best_partition, louvain_communities, G)
            pl.visualize_comparison(
                G, best_partition, louvain_communities, nmi_score, f"gen_{i}"
            )

            # Save information in the DataFrame
            for generation in range(NUM_GENERATIONS):
                data.append(
                    {
                        "generation": generation,
                        "best_history": best_history[generation],
                        "avg_history": avg_history[generation],
                    }
                )
        except KeyboardInterrupt:
            break

    df = pd.DataFrame(data)
    df.to_csv("generations_data.csv", index=False)
    print("DataFrame saved to generations_data.csv")

    # =============================================================================================
    # Extras Visuzalitions
    # ==============================================================================================
    exit(0)

    pl.plot_fitness_history(best_history, avg_history)
    pl.visualize_all(G, best_partition)
    best_fitness = ga.calculate_objectives(G, best_partition)