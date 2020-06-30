from qiskit import QuantumRegister, ClassicalRegister, QuantumCircuit, execute
import numpy as np
import networkx as nx
from scipy.optimize import minimize



def createCircuit_MaxCut(x,G,depth,version=1, applyX=[], usebarrier=False):
    num_V = G.number_of_nodes()
    q = QuantumRegister(num_V)
    c = ClassicalRegister(num_V)
    circ = QuantumCircuit(q,c)
    if len(applyX)==0:
        circ.h(range(num_V))
    else:
        if np.where(np.array(applyX)==1)[0].size>0:
            circ.x(np.where(np.array(applyX)==1)[0])
        circ.h(range(num_V))
    if usebarrier:
        circ.barrier()
    for d in range(depth):
        gamma=x[2*d]
        beta=x[2*d+1]
        for edge in G.edges():
            i=int(edge[0])
            j=int(edge[1])
            w = G[edge[0]][edge[1]]['weight']
            wg = w*gamma
            if version==1:
                circ.cx(q[i],q[j])
                circ.rz(wg,q[j])
                circ.cx(q[i],q[j])
            else:
                circ.cu1(-2*wg, i, j)
                circ.u1(wg, i)
                circ.u1(wg, j)
        if usebarrier:
            circ.barrier()
        circ.rx(2*beta,range(num_V))
        if usebarrier:
            circ.barrier()
    circ.measure(q,c)
    return circ

def cost_MaxCut(x,G):
    C=0
    for edge in G.edges():
        i = int(edge[0])
        j = int(edge[1])
        w = G[edge[0]][edge[1]]['weight']
        C = C + w/2*(1-(2*x[i]-1)*(2*x[j]-1))
    return C

def enumerate(G):
    if (len(G) > 30):
        raise Exception("Too many solutions to enumerate.")

    maxcut = []
    maxcut_value = 0
    N = len(G)
    for i in range(2**N - 1):
        x_bin = format(i, 'b').zfill(N)
        x = [int(j) for j in x_bin]
        c = 0
        for u,v in G.edges():
            c += G[u][v]['weight']/2*(1-(2*x[int(u)]-1)*(2*x[int(v)]-1))

        if (c > maxcut_value):
            maxcut = x
            maxcut_value = c

    return maxcut_value, maxcut

def listSortedCosts_MaxCut(G):
    costs={}
    maximum=0
    solutions=[]
    num_V = G.number_of_nodes()
    for i in range(2**num_V):
        binstring="{0:b}".format(i).zfill(num_V)
        y=[int(i) for i in binstring]
        costs[binstring]=cost_MaxCut(y,G)
    sortedcosts={k: v for k, v in sorted(costs.items(), key=lambda item: item[1])}
    return sortedcosts

def costsHist_MaxCut(G):
    num_V = G.number_of_nodes()
    costs=np.ones(2**num_V)
    for i in range(2**num_V):
        if i%1024*2*2*2==0:
            print(i/2**num_V*100, "%", end='\r')
        binstring="{0:b}".format(i).zfill(num_V)
        y=[int(i) for i in binstring]
        costs[i]=cost_MaxCut(y,G)
    print("100%")
    return costs

def bins_comp_basis(data, G):
    max_solutions=[]
    num_V = G.number_of_nodes()
    bins_states = np.zeros(2**num_V)
    num_shots=0
    num_solutions=0
    max_cost=0
    average_cost=0
    for item, binary_rep in enumerate(data):
        integer_rep=int(str(binary_rep), 2)
        counts=data[str(binary_rep)]
        bins_states[integer_rep] += counts
        num_shots+=counts
        num_solutions+=1
        y=[int(i) for i in str(binary_rep)]
        lc = cost_MaxCut(y,G)
        if lc==max_cost:
            max_solutions.append(y)
        elif lc>max_cost:
            max_solutions=[]
            max_solutions.append(y)
            max_cost=lc
        average_cost+=lc*counts
    return bins_states, max_cost, average_cost/num_shots, max_solutions


def objective_function(params, G, backend, num_shots=8192):
    """
    :return: minus the expectation value (in order to maximize MaxCut configuration)
    NB! If a list of circuits are ran, only returns the expectation value of the first circuit.
    """
    qc = createCircuit_MaxCut(params, G, int(len(params)/2))
    res_data = execute(qc, backend, shots=num_shots).result().results
    E,_ = measurementStatistics_MaxCut(res_data, G)
    return -E[0]

def random_init(depth, weighted):
    """
    Enforces the bounds of gamma and beta based on the graph type.
    :return: np.array on the form (gamma_1, beta_1, gamma_2, ...., gamma_d, beta_d)
    """
    if weighted:
        gamma_list = np.random.uniform(-10,10, size=depth) # Here 10 is arbitrary
    else:
        gamma_list = np.random.uniform(-np.pi / 2, np.pi / 2, size=depth)
    beta_list = np.random.uniform(-np.pi / 4, np.pi / 4, size=depth)
    initial = np.empty((gamma_list.size + beta_list.size,), dtype=gamma_list.dtype)
    initial[0::2] = gamma_list
    initial[1::2] = beta_list
    return initial

def get_constaints_for_COBYLA(depth, weighted):
    """
    :return: List of constraints applying to the parameters
    """
    bounds = []
    if weighted:
        for i in range(depth):
            bounds.append([-10,10]) # Arbitrary choice
            bounds.append([-np.pi/4, np.pi/4])
    else:
        for i in range(depth):
            bounds.append([-np.pi/2, np.pi/2])
            bounds.append([-np.pi/4, np.pi/4])
    cons = []
    for factor in range(len(bounds)):
        lower, upper = bounds[factor]
        l = {'type': 'ineq',
             'fun': lambda x, lb=lower, i=factor: x[i] - lb}
        u = {'type': 'ineq',
             'fun': lambda x, ub=upper, i=factor: ub - x[i]}
        cons.append(l)
        cons.append(u)
    return cons

def optimize_random(K,G, backend, depth=1, weighted=False, num_shots=8192):
    """
    :param K: # Random initializations (RIs)
    :return: Array of best params (on the format where the gammas and betas are intertwined),
    the corresponding best energy value, and the average energy value for all the RIs
    """
    record = -np.inf
    avg_list = np.zeros(K)
    for i in range(K):
        init_params = random_init(depth, weighted)
        cons = get_constaints_for_COBYLA(depth, weighted)
        sol = minimize(objective_function, x0=init_params, method='COBYLA', args=(G, backend, num_shots), constraints=cons)
        params = sol.x
        qc = createCircuit_MaxCut(params, G, depth)
        temp_res_data = execute(qc, backend, shots=num_shots).result().results
        [E],_ = measurementStatistics_MaxCut(temp_res_data, G)
        avg_list[i] = E
        if E>record:
            record = E
            record_params = params
    return record_params, record, np.average(avg_list)

def scale_p(K, G, backend, depth=3, weighted=False, num_shots=8192):
    """
    :return: arrays of the p_values used, the corresponding array for the energy from the optimal
         energy config, and the average energy (for all the RIs at each p value)
    """
    H_list = np.zeros(depth)
    avg_list = np.zeros(depth)
    p_list = np.arange(1, depth + 1, 1)
    for d in range(1, depth + 1):
        temp, H_list[d-1], avg_list[d-1] = optimize_random(K, G, backend, d, weighted, num_shots)
    return p_list, H_list, avg_list



def INTERP_init(params_prev_step):
    """
    Takes the optimal parameters at level p as input and returns the optimal inital guess for
    the optimal paramteres at level p+1. Uses the INTERP formula from the paper by Zhou et. al
    :param params_prev_step: optimal parameters at level p
    :return:
    """
    p = len(params_prev_step)
    params_out_list = np.zeros(p+1)
    params_out_list[0] = params_prev_step[0]
    for i in range(2, p + 1):
        # Next line is clunky, but written this way to accommodate the 1-indexing in the paper
        params_out_list[i - 1] = (i - 1) / p * params_prev_step[i-2] + (p - i + 1) / p * params_prev_step[i-1]
    params_out_list[p] = params_prev_step[p-1]
    return params_out_list

def optimize_INTERP(K, G, backend, depth, weighted=False, num_shots=8192):
    """
    Optimizes the params using the INTERP heuristic
    :return: Array of the optimal parameters, and the correponding energy value
    """
    record = -np.inf
    for i in range(K):
        init_params = np.zeros(2)
        cons = get_constaints_for_COBYLA(1, weighted)
        sol = minimize(objective_function, x0=init_params, method='COBYLA', args=(G, backend, num_shots), constraints=cons)
        params = sol.x
        init_gamma = params[0:1]
        init_beta = params[1:2]
        for p in range(2, depth + 1):
            init_gamma = INTERP_init(init_gamma)
            init_beta = INTERP_init(init_beta)
            init_params = np.zeros(2 * p)
            init_params[0::2] = init_gamma
            init_params[1::2] = init_beta
            cons = get_constaints_for_COBYLA(p, weighted)
            sol = minimize(objective_function, x0=init_params, method='COBYLA', args=(G, backend, num_shots), constraints=cons)
            params = sol.x
            init_gamma = params[0::2]
            init_beta = params[1::2]
        qc = createCircuit_MaxCut(params, G, depth)
        temp_res_data = execute(qc, backend, shots=num_shots).result().results
        [E],_ = measurementStatistics_MaxCut(temp_res_data, G)
        if E>record:
            record = E
            record_params = params
    return record_params, record


def add_weights(G, weighted=False):
    """
    Adds weights G. If weighted, the weights are uniformly distributed from [0,1],
    otherwise all the weights are equal to 1.0. Does not return anything, but modifies
    the input graph.
    :param G:
    :param weighted:
    """
    if weighted:
        for edge in G.edges():
            i=int(edge[0])
            j=int(edge[1])
            E = [(i,j,np.random.uniform())]
            G.add_weighted_edges_from(E)
    else:
        for edge in G.edges():
            i=int(edge[0])
            j=int(edge[1])
            E = [(i,j,1.0)]
            G.add_weighted_edges_from(E)

def measurementStatistics_MaxCut(experiment_results, G):
    """
    Calculates the expectation and variance of the cost function. If
    results from multiple circuits are used as input, each circuit's
    expectation value are returned.
    :param experiment_results: Input on the form execute(...).result().results
    :param G: The graph on which the cost function is defined.
    :return: Lists of expectation values and variances
    """

    expectations = []
    variances = []
    num_qubits = G.number_of_nodes()
    for result in experiment_results:
        n_shots = result.shots
        counts = result.data.counts

        E = 0
        E2 = 0
        for hexkey in list(counts.__dict__.keys()):
            count = getattr(counts, hexkey)
            binstring = "{0:b}".format(int(hexkey,0)).zfill(num_qubits)
            binlist = [int(i) for i in binstring]
            cost = cost_MaxCut(binlist,G)
            E += cost*count/n_shots;
            E2 += cost**2*count/n_shots;

        if n_shots == 1:
            v = 0
        else:
            v = (E2-E**2)*n_shots/(n_shots-1)
        expectations.append(E)
        variances.append(v)
    return expectations, variances

def sampleUntilPrecision_MaxCut(circuit,G,backend,noisemodel,min_n_shots,max_n_shots,E_atol,E_rtol,dv_rtol,confidence_index):
    """
    Samples from the circuit and calculates the cost function until the specified
    error tolerances are satisfied. This may include several repetitions, either if
    the number of initial shots was too small, or if the variance estimate changed
    to a large degree since the last repetition, meaning that the required shot
    estimate was inaccurate.

    :param circuit: The circuit that will be sampled.
    :param G: The graph on which the cost function is defined.
    :param backend: The backend that will execute the circuit.
    :param noisemodel: The noisemodel to use, e.g. when simulating.
    :param min_n_shots: The minimum number of shots to be executed.
    :param max_n_shots: The maximum number of shots to be executed.
    :param E_atol: Absolute error tolerance for the expectation value.
    :param E_rtol: Relative error tolerance for the expectation value.
    :param dv_rtol: Relative change in variance tolerated without repeating.
    :param confidence_index: The degree of confidence required.
    :return: Lists of expectation values, variances and shots each repetition.
    """

    E_tot = 0
    v_tot = 0
    n_tot = 0

    E_list = []
    v_list = []
    n_list = []

    n_req = min_n_shots
    v_prev = v_tot
    while n_tot < n_req and np.abs(v_tot-v_prev) >= dv_rtol*v_prev:
        v_prev = v_tot
        n_cur = n_req - n_tot
        experiment = execute(circuit, backend, noise_model=noisemodel, shots=n_cur)

        [E_cur],[v_cur] = measurementStatistics_MaxCut(experiment.result().results,G)
        E_tot = (n_tot*E_tot + n_cur*E_cur)/(n_tot+n_cur)
        v_tot = ((n_tot-1)*v_tot + (n_cur-1)*v_cur)/(n_tot+n_cur-1)
        n_tot = n_req
        E_list.append(E_tot)
        v_list.append(v_tot)
        n_list.append(n_cur)

        E_tol = min(E_atol,E_rtol*E_tot)
        n_req = int(np.ceil(confidence_index**2*v_tot/E_tol**2))

        if n_req > max_n_shots:
            print('Warning: need %d samples to satisfy tolerance %.2e, but max_n_shots = %d.' % (n_req, E_tol, max_n_shots))
            n_req = max_n_shots

    return E_list,v_list,n_list
