import argparse
import csv
import datetime
import json
import os
import random
import string
import subprocess
import time

import pandas as pd
import requests

from visualisation import create_squad_timeline

BASE_URL = "https://en.fantasy.obosdamallsvenskan.se/api"


def get_random_id(n):
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def load_config_files(config_paths):
    """
    Load and merge multiple configuration files.
    Files are merged in order, with later files overriding earlier ones.
    """
    merged_config = {}
    if not config_paths:
        return merged_config

    paths = config_paths.split(";")
    for path in paths:
        path = path.strip()
        if not path:
            continue
        try:
            with open(path) as f:
                config = json.load(f)
                merged_config.update(config)
        except FileNotFoundError:
            print(f"Warning: Configuration file {path} not found")
        except json.JSONDecodeError:
            print(f"Warning: Configuration file {path} is not valid JSON")

    return merged_config


def is_latest_version():
    try:
        # Get the current branch name
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()

        # Fetch the latest updates from the remote
        subprocess.run(["git", "fetch"], check=True, stderr=subprocess.DEVNULL)

        # Check if there are commits in the remote branch not in the local branch
        updates = subprocess.check_output(["git", "rev-list", f"HEAD..origin/{branch}"], stderr=subprocess.DEVNULL, text=True).strip()

        if updates:
            print("Your repository is not up-to-date. Please pull the latest changes.")
            return False
        else:
            print("Your repository is up-to-date.")
            return True
    except subprocess.CalledProcessError:
        print("Error: Could not check the repository status.")
        return False


def solve_regular(runtime_options=None):
    from dev import generate_team_json, prep_data, solve_multi_period_fpl

    # Create a base parser first for the --config argument
    # remaining_args is all the command line args that aren't --config
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument("--config", type=str, help="Path to one or more configuration files (semicolon-delimited)")
    base_args, remaining_args = base_parser.parse_known_args()

    # Load base configuration file
    with open("settings.json") as f:
        options = json.load(f)

    # Load and merge additional configuration files if specified
    if base_args.config:
        config_options = load_config_files(base_args.config)
        options.update(config_options)  # Override base config with additional configs

    # Create the full parser with all configuration options
    parser = argparse.ArgumentParser(parents=[base_parser])
    for key, value in options.items():
        if value is None or isinstance(value, (list, dict)):
            parser.add_argument(f"--{key}", default=value)
            continue
        parser.add_argument(f"--{key}", type=type(value), default=value)

    # Parse remaining arguments, which will take highest priority
    args = vars(parser.parse_args(remaining_args))

    # this code block is to look at command line arguments (read as a string) and determine what type
    # they should be when there is no default argument type set by the code above
    for key, value in args.items():
        if key not in options:
            continue
        if value == options[key]:  # skip anything that hasn't been edited by command line argument
            continue

        if options[key] is None or isinstance(options[key], (list, dict)):
            if value.isdigit():
                args[key] = int(value)
                continue

            try:
                args[key] = float(value)
                continue
            except ValueError:
                pass

            if value[0] in "[{":
                try:
                    args[key] = json.loads(value)
                    continue
                except json.JSONDecodeError:
                    value = value.replace("'", '"')
                    args[key] = json.loads(value)
                    continue
                finally:
                    pass

            try:
                args[key] = str(value)
                continue
            except (SyntaxError, ValueError):
                pass

            print(f"Problem with CL argument: {key}. Original value: {options[key]}, New value: {value}")

    cli_options = {k: v for k, v in args.items() if v is not None and k != "config"}

    # Update options with CLI arguments (highest priority)
    options.update(cli_options)

    if runtime_options is not None:
        options.update(runtime_options)

    if options.get("cbc_path") != "" and options.get("cbc_path") is not None:
        os.environ["PATH"] += os.pathsep + options.get("cbc_path")

    if options.get("preseason"):
        my_data = {"picks": [], "chips": [], "transfers": {"limit": None, "cost": 4, "bank": 1000, "value": 0}}
    else:
        if options.get("team_data", "json").lower() == "id":
            team_id = options.get("team_id", None)
            if team_id is None:
                print("You must supply your team_id in settings.json")
                exit(0)
            my_data = generate_team_json(team_id, options)
        else:
            try:
                with open("data/team.json") as f:
                    my_data = json.load(f)
                price_changes = options.get("price_changes", [])
                if price_changes:
                    my_squad_ids = [x["element"] for x in my_data["picks"]]
                    with requests.Session() as s:
                        r = s.get(f"{BASE_URL}/bootstrap-static/").json()["elements"]
                    current_prices = {x["id"]: x["now_cost"] for x in r if x["id"] in my_squad_ids}
                    for pid, change in price_changes:
                        if pid not in my_squad_ids:
                            continue
                        new_price = current_prices[pid] + change
                        player = [x for x in my_data["picks"] if x["element"] == pid][0]
                        if player["purchase_price"] >= new_price:
                            player["selling_price"] = new_price
                        else:
                            player["selling_price"] = player["purchase_price"] + (new_price - player["purchase_price"]) // 2
            except FileNotFoundError:
                print("Couldn't find a data/team.json file")
                exit(0)
    data = prep_data(my_data, options)

    response = solve_multi_period_fpl(data, options)
    run_id = get_random_id(5)
    options["run_id"] = run_id
    for result in response:
        iter = result["iter"]
        time_now = datetime.datetime.now()
        stamp = time_now.strftime("%Y-%m-%d_%H-%M-%S")
        if not (os.path.exists("data/results/")):
            os.mkdir("data/results/")

        solve_name = options.get("solve_name", "regular")
        if options.get("binary_file_name"):
            bfn = options.get("binary_file_name")
            filename = f"{solve_name}_{bfn}_{stamp}_{run_id}_{iter}"
        else:
            filename = f"{solve_name}_{stamp}_{run_id}_{iter}"
        result["picks"].to_csv("data/results/" + filename + ".csv")

        if options.get("export_image", False):
            create_squad_timeline(current_squad=data["initial_squad"], statistics=result["statistics"], picks=result["picks"], filename=filename)

    print("Result Summary")
    result_table = pd.DataFrame(response)
    result_table = result_table.sort_values(by="score", ascending=False)
    print(result_table[["iter", "sell", "buy", "chip", "score"]].to_string(index=False))

    if len(options.get("report_decay_base", [])) > 0:
        try:
            print("Decay Metrics")
            metrics_df = pd.DataFrame([{"iter": result["iter"], **result["decay_metrics"]} for result in response])
            print(metrics_df)

        except Exception:
            pass

    # Detailed print
    for result in response:
        print(result["summary"])
        picks = result["picks"]
        gws = picks["week"].unique()
        print(f"Solution {result['iter'] + 1}")
        for gw in gws:
            line_text = ""
            chip_text = picks[picks["week"] == gw].iloc[0]["chip"]
            if chip_text != "":
                line_text += "(" + chip_text + ") "
            sell_text = ", ".join(picks[(picks["week"] == gw) & (picks["transfer_out"] == 1)]["name"].to_list())
            buy_text = ", ".join(picks[(picks["week"] == gw) & (picks["transfer_in"] == 1)]["name"].to_list())

            if sell_text != "" or buy_text != "":
                line_text += sell_text + " -> " + buy_text
            else:
                line_text += "Roll"
            print(f"\tGW{gw}: {line_text}")

        solutions_file = options.get("solutions_file")
        if solutions_file:
            write_line_to_file(solutions_file, result, options)


def write_line_to_file(filename, result, options):
    t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    gw = min(result["picks"]["week"])
    score = round(result["score"], 3)
    picks = result["picks"]

    caps = ", ".join(picks[(picks["week"] == gw) & (picks["captain"] > 0.5)]["name"].values)
    vcaps = ", ".join(picks[(picks["week"] == gw) & (picks["vicecaptain"] > 0.5)]["name"].values)

    run_id = options["run_id"]
    iter = result["iter"]
    team_id = options.get("team_id")
    chips = [options.get(x) for x in ["use_wc", "use_lr", "use_dd", "use_ptb"]]
    sell_text = ", ".join(picks[(picks["week"] == gw) & (picks["transfer_out"] == 1)]["name"].to_list())
    buy_text = ", ".join(picks[(picks["week"] == gw) & (picks["transfer_in"] == 1)]["name"].to_list())

    headers = ["run_id", "iter", "user_id", "wc", "lr", "dd", "ptb", "cap", "vcap", "sell", "buy", "score", "datetime"]
    data = [run_id, iter, team_id] + chips + [caps, vcaps, sell_text, buy_text, score, t]
    if options.get("show_summary", False):
        headers.append("summary")
        data.append(result["summary"])

    if not os.path.exists(filename):
        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    with open(filename, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(data)


if __name__ == "__main__":
    solve_regular()
