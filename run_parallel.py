import subprocess
from concurrent.futures import ProcessPoolExecutor
from itertools import product


def get_dict_combinations(my_dict):
    keys = my_dict.keys()
    for key in keys:
        if my_dict[key] is None or len(my_dict[key]) == 0:
            my_dict[key] = [None]
    all_combs = [dict(zip(my_dict.keys(), values)) for values in product(*my_dict.values())]
    feasible_combs = []
    for comb in all_combs:
        comb_copy = comb.copy()
        c_values = [i for i in comb_copy.values() if i is not None]
        if len(c_values) == len(set(c_values)):
            feasible_combs.append(comb)
    return feasible_combs


def run_script(command):
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        return f'Command "{command}" failed with exit code {e.returncode}.\n{e}\n\n'


def run_parallel_solves(jobs, max_workers=8):
    # change this bit to be the way you run a standard solve.
    # e.g. for me, I do `.venv/bin/python solve.py`, you might do `python solve.py` or `python3 solve.py` etc.
    # don't forget the space afterwards
    jobs = [".venv/bin/python solve.py " + " ".join(f"--use_{k} {v}" for k, v in combination.items() if v) for combination in combinations]
    print(len(jobs))

    # Use ProcessPoolExecutor to run commands in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(run_script, jobs))

    for result in results:
        if result:
            print(result)


if __name__ == "__main__":
    chip_gameweeks = {
        "wc": [3, 4, 5],
        "ptb": [1, 2, 3, 4],
        "lr": [2, 3, 4],
        "dd": [1, 2, 3, 4],
    }

    combinations = get_dict_combinations(chip_gameweeks)
    run_parallel_solves(combinations)
