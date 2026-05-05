import requests
from os import environ
from pathlib import Path
from time import sleep
import time
import json
import pandas as pd
import random
import pickle
import csv
from itertools import product
from itertools import combinations
from collections import defaultdict
from datetime import date, datetime
 
PROJECT_ROOT = Path(__file__).resolve().parent
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.txt"
RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_RESULTS_CSV = RESULTS_DIR / "simulation_results.csv"


def load_credentials():
    username = environ.get("WQB_USERNAME")
    password = environ.get("WQB_PASSWORD")
    if username and password:
        return username, password

    with open(CREDENTIALS_PATH, "r") as f:
        credentials = json.load(f)
    return credentials["username"], credentials["password"]


username, password = load_credentials()
 
basic_ops = ["reverse", "inverse", "rank", "zscore", "quantile", "normalize"]
 
ts_ops = ["ts_rank", "ts_zscore", "ts_delta",  "ts_sum", "ts_delay", 
          "ts_std_dev", "ts_mean",  "ts_arg_min", "ts_arg_max","ts_scale", "ts_quantile"]
 
ops_set = basic_ops + ts_ops 


def format_alpha_metrics(metrics):
    alpha_id = metrics.get("alpha_id") or "-"
    sharpe = metrics.get("sharpe")
    fitness = metrics.get("fitness")
    turnover = metrics.get("turnover")
    margin = metrics.get("margin")
    return (
        f"id={alpha_id:<14} "
        f"sharpe={(sharpe if sharpe is not None else 0):>6.3f} "
        f"fitness={(fitness if fitness is not None else 0):>6.3f} "
        f"turnover={(turnover if turnover is not None else 0):>6.3f} "
        f"margin={(margin if margin is not None else 0):>8.4f} "
        f"decay={metrics.get('decay', '-')}"
    )


def print_alpha_result(metrics, prefix="Alpha"):
    print(f"{prefix}: {format_alpha_metrics(metrics)}")
    exp = metrics.get("exp")
    if exp:
        print(f"  expr: {exp}")


def normalize_brain_date(value, year=None):
    if len(value) == 10 and value[4] == "-":
        return value
    resolved_year = year or date.today().year
    return f"{resolved_year}-{value}"


def result_row_from_metrics(metrics, region=None, universe=None, neutralization=None, status=None):
    return {
        "logged_at": datetime.now().isoformat(timespec="seconds"),
        "alpha_id": metrics.get("alpha_id"),
        "status": status,
        "region": region,
        "universe": universe,
        "neutralization": neutralization,
        "sharpe": metrics.get("sharpe"),
        "fitness": metrics.get("fitness"),
        "turnover": metrics.get("turnover"),
        "margin": metrics.get("margin"),
        "decay": metrics.get("decay"),
        "dateCreated": metrics.get("dateCreated"),
        "expr": metrics.get("exp"),
    }


def append_result_csv(metrics, csv_path=DEFAULT_RESULTS_CSV, region=None, universe=None, neutralization=None, status=None):
    if not csv_path:
        return
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    row = result_row_from_metrics(metrics, region, universe, neutralization, status)
    fieldnames = list(row.keys())
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def load_logged_expressions(csv_path=DEFAULT_RESULTS_CSV):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return set()
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Could not read existing result log {csv_path}: {e}")
        return set()
    if "expr" not in df.columns:
        return set()
    return set(df["expr"].dropna().astype(str))

def login():
 
    # Create a session to persistently store the headers
    s = requests.Session()
    # Save credentials into session
    s.auth = (username, password)
 
    # Send a POST request to the /authentication API
    response = s.post('https://api.worldquantbrain.com/authentication')
    try:
        auth_payload = response.json()
        user_id = auth_payload.get("user", {}).get("id")
        permissions = auth_payload.get("token", {}).get("permissions", [])
        s.brain_user_id = user_id
        s.brain_permissions = permissions
        print(
            "Authentication:",
            json.dumps(
                {
                    "status_code": response.status_code,
                    "user_id": user_id,
                    "permissions": permissions,
                },
                ensure_ascii=False,
            ),
        )
    except ValueError:
        s.brain_user_id = None
        s.brain_permissions = []
        print(response.content)
    return s  


def submit_simulation_request(s, sim_data):
    response = s.post('https://api.worldquantbrain.com/simulations', json=sim_data)
    response_text = response.text
    try:
        response_json = response.json()
    except ValueError:
        response_json = None
    return response, response_text, response_json


def wait_for_simulation_progress(s, progress_url):
    while True:
        simulation_progress = s.get(progress_url)
        retry_after = simulation_progress.headers.get("Retry-After")
        if retry_after:
            sleep(float(retry_after))
            continue
        return simulation_progress


def submit_single_simulation_with_retry(s, sim_data, task_idx, alpha_idx, max_retries=20):
    retry_count = 0
    while True:
        response, response_text, response_json = submit_simulation_request(s, sim_data)
        if response.status_code == 201:
            return response.headers.get('Location')

        if response.status_code == 429:
            retry_count += 1
            wait_seconds = float(response.headers.get("Retry-After", 15))
            print(
                f"Single simulation {task_idx}.{alpha_idx} hit concurrency limit, "
                f"waiting {wait_seconds} seconds before retry "
                f"({retry_count}/{max_retries})"
            )
            if retry_count >= max_retries:
                print(
                    f"Single simulation {task_idx}.{alpha_idx} exceeded max retries, "
                    "skipping this alpha"
                )
                return None
            sleep(wait_seconds)
            continue

        print(
            f"Single simulation {task_idx}.{alpha_idx} failed "
            f"(status {response.status_code}): {response_text}"
        )
        if response_json is not None:
            print(f"Single simulation {task_idx}.{alpha_idx} JSON response: {response_json}")
        return None


def has_multi_simulation_permission(s):
    permissions = {str(permission).lower() for permission in getattr(s, "brain_permissions", [])}
    multi_permission_keywords = (
        "consultant",
        "advisor",
        "multi_simulate",
        "multi-simulate",
        "batch_simulate",
        "batch-simulate",
    )
    return any(keyword in permission for permission in permissions for keyword in multi_permission_keywords)


def wait_for_single_simulation_completion(s, progress_url, task_idx, alpha_idx):
    simulation_progress = wait_for_simulation_progress(s, progress_url)
    try:
        progress_json = simulation_progress.json()
    except ValueError:
        print(f"Single simulation {task_idx}.{alpha_idx} returned non-JSON progress response")
        return None

    status = progress_json.get("status", 0)
    alpha_id = progress_json.get("alpha")
    print(f"Single simulation {task_idx}.{alpha_idx} finished with status={status}, alpha_id={alpha_id}")
    return progress_json
 
def set_alpha_properties(
    s,
    alpha_id,
    name: str = None,
    color: str = None,
    selection_desc: str = "None",
    combo_desc: str = "None",
    tags: str = ["ace_tag"],
):
    """
    Function changes alpha's description parameters
    """
 
    params = {
        "color": color,
        "name": name,
        "tags": tags,
        "category": None,
        "regular": {"description": None},
        "combo": {"description": combo_desc},
        "selection": {"description": selection_desc},
    }
    response = s.patch(
        "https://api.worldquantbrain.com/alphas/" + alpha_id, json=params
    )
    if response.status_code not in {200, 201, 204}:
        print(f"Failed to update alpha {alpha_id}: {response.status_code} {response.text}")
    return response
 
def mark_alpha_for_submission(
    s,
    alpha_id,
    prod_correlation=None,
    color="GREEN",
    tags=None,
):
    tags = tags or ["submittable", "wq-assistant"]
    selection_desc = "Passed submission checks"
    if prod_correlation is not None:
        selection_desc += f"; PROD_CORRELATION={prod_correlation}"

    return set_alpha_properties(
        s,
        alpha_id,
        color=color,
        selection_desc=selection_desc,
        combo_desc="Marked by wq-assistant after submission check",
        tags=tags,
    )


def check_submission(
    alpha_bag,
    gold_bag,
    start,
    mark_passed=True,
    mark_color="GREEN",
    mark_tags=None,
):
    depot = []
    s = login()
    for idx, g in enumerate(alpha_bag):
        if idx < start:
            continue
        if idx % 5 == 0:
            print(idx)
        if idx % 200 == 0:
            s = login()
        #print(idx)
        pc = get_check_submission(s, g)
        if pc == "sleep":
            sleep(100)
            s = login()
            alpha_bag.append(g)
        elif pc != pc:
            # pc is nan
            print("check self-corrlation error")
            sleep(100)
            alpha_bag.append(g)
        elif pc == "fail":
            continue
        elif pc == "error":
            depot.append(g)
        else:
            print(g)
            gold_bag.append((g, pc))
            if mark_passed:
                mark_alpha_for_submission(s, g, pc, color=mark_color, tags=mark_tags)
    print(depot)
    return gold_bag

def get_check_submission(s, alpha_id):
    while True:
        result = s.get("https://api.worldquantbrain.com/alphas/" + alpha_id + "/check")
        if "retry-after" in result.headers:
            time.sleep(float(result.headers["Retry-After"]))
        else:
            break
    try:
        if result.json().get("is", 0) == 0:
            print("logged out")
            return "sleep"
        checks_df = pd.DataFrame(
                result.json()["is"]["checks"]
        )
        pc = checks_df[checks_df.name == "PROD_CORRELATION"]["value"].values[0]
        if not any(checks_df["result"] == "FAIL"):
            return pc
        else:
            return "fail"
    except:
        print("catch: %s"%(alpha_id))
        return "error"
            
def get_vec_fields(fields):

    vec_ops = ["vec_avg", "vec_sum"]
    vec_fields = []
 
    for field in fields:
        for vec_op in vec_ops:
            if vec_op == "vec_choose":
                vec_fields.append("%s(%s, nth=-1)"%(vec_op, field))
                vec_fields.append("%s(%s, nth=0)"%(vec_op, field))
            else:
                vec_fields.append("%s(%s)"%(vec_op, field))
 
    return(vec_fields)

def dedupe_alpha_list(alpha_list):
    seen = set()
    deduped = []
    for alpha, decay in alpha_list:
        key = (alpha, decay)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((alpha, decay))
    return deduped


def prepare_alpha_list(alpha_list, max_count=None, shuffle=True, skip_logged=True, results_csv=DEFAULT_RESULTS_CSV):
    prepared = dedupe_alpha_list(alpha_list)
    original_count = len(prepared)
    if skip_logged:
        logged_expressions = load_logged_expressions(results_csv)
        prepared = [(alpha, decay) for alpha, decay in prepared if alpha not in logged_expressions]
        skipped_count = original_count - len(prepared)
        if skipped_count:
            print(f"Skipped {skipped_count} expressions already present in {results_csv}")
    if shuffle:
        random.shuffle(prepared)
    if max_count is not None:
        prepared = prepared[:max_count]
    print(f"Prepared {len(prepared)} unique alpha expressions")
    return prepared


def multi_simulate(alpha_pools, neut, region, universe, start, mode="auto", results_csv=DEFAULT_RESULTS_CSV):

    s = login()

    brain_api_url = 'https://api.worldquantbrain.com'
    normalized_mode = str(mode).lower()
    if normalized_mode not in {"auto", "single", "multi"}:
        raise ValueError("mode must be one of: auto, single, multi")

    if normalized_mode == "single":
        allow_multi_simulation = False
        print("Simulation mode: single")
    elif normalized_mode == "multi":
        allow_multi_simulation = True
        print("Simulation mode: multi")
    else:
        allow_multi_simulation = has_multi_simulation_permission(s)
        mode_name = "multi" if allow_multi_simulation else "single"
        print(
            "Simulation mode: %s (auto, permissions=%s)"
            % (mode_name, getattr(s, "brain_permissions", []))
        )

    for x, pool in enumerate(alpha_pools):
        if x < start: continue
        progress_urls = []
        for y, task in enumerate(pool):
            # 10 tasks, 10 alpha in each task
            sim_data_list = generate_sim_data(task, region, universe, neut)
            try:
                if allow_multi_simulation:
                    simulation_response, simulation_text, simulation_json = submit_simulation_request(s, sim_data_list)
                    
                    # Check response status
                    if simulation_response.status_code == 403:
                        print("Multi-simulation rejected, switching to single alpha mode")
                        print(f"Response: {simulation_text}")
                        allow_multi_simulation = False
                    elif simulation_response.status_code != 201:
                        print(f"Error submitting simulation (status {simulation_response.status_code}): {simulation_text}")
                        if simulation_json is not None:
                            print(f"JSON response: {simulation_json}")
                        sleep(600)
                        s = login()
                        continue
                    else:
                        simulation_progress_url = simulation_response.headers.get('Location')
                        if not simulation_progress_url:
                            print(f"No Location header in response: {simulation_response.headers}")
                            sleep(600)
                            s = login()
                            continue
                        progress_urls.append(simulation_progress_url)
                        continue

                for idx, sim_data in enumerate(sim_data_list):
                    simulation_progress_url = submit_single_simulation_with_retry(s, sim_data, y, idx)
                    if not simulation_progress_url:
                        continue

                    progress_json = wait_for_single_simulation_completion(s, simulation_progress_url, y, idx)
                    alpha_id = progress_json.get("alpha") if progress_json else None
                    status = progress_json.get("status") if progress_json else None
                    if alpha_id:
                        metrics = locate_alpha(s, alpha_id)
                        print_alpha_result(metrics, prefix=f"Result {x}.{y}.{idx}")
                        append_result_csv(metrics, results_csv, region, universe, neut, status)
            except PermissionError as e:
                print(f"Permission error: {e}")
                raise
            except Exception as e:
                print(f"Error during simulation submission: {e}")
                sleep(600)
                s = login()

        print("pool %d task %d post done"%(x,y))

        last_progress_idx = -1
        for j, progress in enumerate(progress_urls):
            last_progress_idx = j
            try:
                simulation_progress = wait_for_simulation_progress(s, progress)

                status = simulation_progress.json().get("status", 0)
                if status != "COMPLETE":
                    print("Not complete : %s"%(progress))
                progress_json = simulation_progress.json()
                alpha_id = progress_json.get("alpha")
                if alpha_id:
                    metrics = locate_alpha(s, alpha_id)
                    print_alpha_result(metrics, prefix=f"Result {x}.{j}")
                    append_result_csv(metrics, results_csv, region, universe, neut, status)

                children = progress_json.get("children", []) or []
                for child_idx, child in enumerate(children):
                    child_progress = wait_for_simulation_progress(s, brain_api_url + "/simulations/" + child)
                    child_progress_json = child_progress.json()
                    child_alpha_id = child_progress_json.get("alpha")
                    child_status = child_progress_json.get("status")
                    if child_alpha_id:
                        metrics = locate_alpha(s, child_alpha_id)
                        print_alpha_result(
                            metrics,
                            prefix=f"Result {x}.{j}.{child_idx}",
                        )
                        append_result_csv(metrics, results_csv, region, universe, neut, child_status)
            except KeyError:
                print("look into: %s"%progress)
            except Exception as e:
                print(f"Error reading simulation result {progress}: {e}")


        print("pool %d task %d simulate done"%(x, last_progress_idx))
    
    print("Simulate done")

def generate_sim_data(alpha_list, region, uni, neut):
    sim_data_list = []
    for alpha, decay in alpha_list:
        simulation_data = {
            'type': 'REGULAR',
            'settings': {
                'instrumentType': 'EQUITY',
                'region': region,
                'universe': uni,
                'delay': 1,
                'decay': decay,
                'neutralization': neut,
                'truncation': 0.08,
                'pasteurization': 'ON',
                'testPeriod': 'P2Y',
                'unitHandling': 'VERIFY',
                'nanHandling': 'ON',
                'language': 'FASTEXPR',
                'visualization': False,
            },
            'regular': alpha}

        sim_data_list.append(simulation_data)
    return sim_data_list

def load_task_pool(alpha_list, limit_of_children_simulations, limit_of_multi_simulations):
    '''
    Input:
        alpha_list : list of (alpha, decay) tuples
        limit_of_multi_simulations : number of children simulation in a multi-simulation
        limit_of_multi_simulations : number of simultaneous multi-simulations
    Output:
        task : [10 * (alpha, decay)] for a multi-simulation
        pool : [10 * [10 * (alpha, decay)]] for simultaneous multi-simulations
        pools : [[10 * [10 * (alpha, decay)]]]

    '''
    tasks = [alpha_list[i:i + limit_of_children_simulations] for i in range(0, len(alpha_list), limit_of_children_simulations)]
    pools = [tasks[i:i + limit_of_multi_simulations] for i in range(0, len(tasks), limit_of_multi_simulations)]
    return pools

def get_datasets(
    s,
    instrument_type: str = 'EQUITY',
    region: str = 'USA',
    delay: int = 1,
    universe: str = 'TOP3000'
):
    url = "https://api.worldquantbrain.com/data-sets?" +\
        f"instrumentType={instrument_type}&region={region}&delay={str(delay)}&universe={universe}"
    result = s.get(url)
    datasets_df = pd.DataFrame(result.json()['results'])
    return datasets_df
 
def get_datafields(
    s,
    instrument_type: str = 'EQUITY',
    region: str = 'USA',
    delay: int = 1,
    universe: str = 'TOP3000',
    dataset_id: str = '',
    search: str = ''
):
    if len(search) == 0:
        url_template = "https://api.worldquantbrain.com/data-fields?" +\
            f"&instrumentType={instrument_type}" +\
            f"&region={region}&delay={str(delay)}&universe={universe}&dataset.id={dataset_id}&limit=50" +\
            "&offset={x}"
        response = s.get(url_template.format(x=0))
        if response.status_code != 200:
            print(f"Error getting count: {response.status_code} - {response.text}")
            raise Exception(f"API Error: {response.text}")
        response_json = response.json()
        count = response_json.get('count', 0)
        print(f"Got count: {count}")
        
    else:
        url_template = "https://api.worldquantbrain.com/data-fields?" +\
            f"&instrumentType={instrument_type}" +\
            f"&region={region}&delay={str(delay)}&universe={universe}&limit=50" +\
            f"&search={search}" +\
            "&offset={x}"
        count = 100
    
    datafields_list = []
    for x in range(0, count, 50):
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            datafields = s.get(url_template.format(x=x))
            
            if datafields.status_code == 429:
                # Rate limit exceeded, wait and retry
                retry_count += 1
                wait_time = 2 ** retry_count  # 2, 4, 8 seconds
                print(f"Rate limit exceeded at offset {x}. Waiting {wait_time} seconds (attempt {retry_count}/{max_retries})...")
                sleep(wait_time)
                continue
            elif datafields.status_code != 200:
                print(f"Error at offset {x}: {datafields.status_code} - {datafields.text}")
                raise Exception(f"API Error at offset {x}: {datafields.text}")
            
            # Success
            response_json = datafields.json()
            if 'results' not in response_json:
                print(f"Warning: 'results' not found in response at offset {x}")
                print(f"Response keys: {response_json.keys()}")
                print(f"Full response: {response_json}")
                break
            datafields_list.append(response_json['results'])
            break
        else:
            # Max retries exceeded
            raise Exception(f"API rate limit exceeded at offset {x}, max retries reached")
 
    datafields_list_flat = [item for sublist in datafields_list for item in sublist]
 
    datafields_df = pd.DataFrame(datafields_list_flat)
    return datafields_df

def process_datafields(df, data_type):

    if data_type == "matrix":
        datafields = df[df['type'] == "MATRIX"]["id"].tolist()
    elif data_type == "vector":
        datafields = get_vec_fields(df[df['type'] == "VECTOR"]["id"].tolist())
    else:
        raise ValueError("data_type must be either 'matrix' or 'vector'")

    tb_fields = []
    for field in datafields:
        tb_fields.append("winsorize(ts_backfill(%s, 120), std=4)"%field)
    return tb_fields
 
def view_alphas(gold_bag):
    s = login()
    sharp_list = []
    for gold, pc in gold_bag:
        metrics = locate_alpha(s, gold)
        metrics["prod_correlation"] = pc
        sharp_list.append(metrics)

    sharp_list.sort(reverse=True, key=lambda x: x.get("sharpe") or 0)
    for i, metrics in enumerate(sharp_list, start=1):
        print_alpha_result(metrics, prefix=f"Candidate {i}")
        print(f"  prod_correlation: {metrics.get('prod_correlation')}")
 
def locate_alpha(s, alpha_id):
    while True:
        alpha = s.get("https://api.worldquantbrain.com/alphas/" + alpha_id)
        if "retry-after" in alpha.headers:
            time.sleep(float(alpha.headers["Retry-After"]))
        else:
            break
    string = alpha.content.decode('utf-8')
    metrics = json.loads(string)
    #print(metrics["regular"]["code"])
    
    dateCreated = metrics["dateCreated"]
    sharpe = metrics["is"]["sharpe"]
    fitness = metrics["is"]["fitness"]
    turnover = metrics["is"]["turnover"]
    margin = metrics["is"]["margin"]
    decay = metrics["settings"]["decay"]
    exp = metrics['regular']['code']

    return {
        "alpha_id": alpha_id,
        "exp": exp,
        "sharpe": sharpe,
        "turnover": turnover,
        "fitness": fitness,
        "margin": margin,
        "dateCreated": dateCreated,
        "decay": decay,
    }
 
 
def get_alphas(start_date, end_date, sharpe_th, fitness_th, region, alpha_num, usage, year=None):
    s = login()
    output = []
    start_date = normalize_brain_date(start_date, year)
    end_date = normalize_brain_date(end_date, year)
    # 3E large 3C less
    count = 0
    for i in range(0, alpha_num, 100):
        print(i)
        url_e = "https://api.worldquantbrain.com/users/self/alphas?limit=100&offset=%d"%(i) \
                + "&status=UNSUBMITTED%1FIS_FAIL&dateCreated%3E=" + start_date  \
                + "T00:00:00-04:00&dateCreated%3C" + end_date \
                + "T00:00:00-04:00&is.fitness%3E" + str(fitness_th) + "&is.sharpe%3E" \
                + str(sharpe_th) + "&settings.region=" + region + "&order=-is.sharpe&hidden=false&type!=SUPER"
        url_c = "https://api.worldquantbrain.com/users/self/alphas?limit=100&offset=%d"%(i) \
                + "&status=UNSUBMITTED%1FIS_FAIL&dateCreated%3E=" + start_date  \
                + "T00:00:00-04:00&dateCreated%3C" + end_date \
                + "T00:00:00-04:00&is.fitness%3C-" + str(fitness_th) + "&is.sharpe%3C-" \
                + str(sharpe_th) + "&settings.region=" + region + "&order=is.sharpe&hidden=false&type!=SUPER"
        urls = [url_e]
        if usage != "submit":
            urls.append(url_c)
        for url in urls:
            response = s.get(url)
            #print(response.json())
            try:
                alpha_list = response.json()["results"]
                #print(response.json())
                for j in range(len(alpha_list)):
                    alpha_id = alpha_list[j]["id"]
                    dateCreated = alpha_list[j]["dateCreated"]
                    sharpe = alpha_list[j]["is"]["sharpe"]
                    fitness = alpha_list[j]["is"]["fitness"]
                    turnover = alpha_list[j]["is"]["turnover"]
                    margin = alpha_list[j]["is"]["margin"]
                    longCount = alpha_list[j]["is"]["longCount"]
                    shortCount = alpha_list[j]["is"]["shortCount"]
                    decay = alpha_list[j]["settings"]["decay"]
                    exp = alpha_list[j]['regular']['code']
                    count += 1
                    #if (sharpe > 1.2 and sharpe < 1.6) or (sharpe < -1.2 and sharpe > -1.6):
                    if (longCount + shortCount) > 100:
                        if sharpe < -sharpe_th:
                            exp = "-%s"%exp
                        rec = [alpha_id, exp, sharpe, turnover, fitness, margin, dateCreated, decay]
                        print_alpha_result(
                            {
                                "alpha_id": alpha_id,
                                "exp": exp,
                                "sharpe": sharpe,
                                "fitness": fitness,
                                "turnover": turnover,
                                "margin": margin,
                                "dateCreated": dateCreated,
                                "decay": decay,
                            },
                            prefix="Tracked",
                        )
                        if turnover > 0.7:
                            rec.append(decay*4)
                        elif turnover > 0.6:
                            rec.append(decay*3+3)
                        elif turnover > 0.5:
                            rec.append(decay*3)
                        elif turnover > 0.4:
                            rec.append(decay*2)
                        elif turnover > 0.35:
                            rec.append(decay+4)
                        elif turnover > 0.3:
                            rec.append(decay+2)
                        output.append(rec)
            except:
                print("%d finished re-login"%i)
                s = login()

    print("count: %d"%count)
    return output
 
def transform(next_alpha_recs, region):
    output = []
    for rec in next_alpha_recs:
        
        decay = rec[-1]
        exp = rec[1]
        output.append([exp,decay])
    output_dict = {region : output}
    return output_dict

def prune(next_alpha_recs, prefix, keep_num):
    # prefix is the datafield prefix, fnd6, mdl175 ...
    # keep_num is the num of top sharpe same-datafield alpha
    output = []
    num_dict = defaultdict(int)
    for rec in next_alpha_recs:
        exp = rec[1]
        field = exp.split(prefix)[-1].split(",")[0]
        sharpe = rec[2]
        if sharpe < 0:
            field = "-%s"%field
        if num_dict[field] < keep_num:
            num_dict[field] += 1
            decay = rec[-1]
            exp = rec[1]
            output.append([exp,decay])
    return output

def first_order_factory(fields, ops_set):
    alpha_set = []
    #for field in fields:
    for field in fields:
        #reverse op does the work
        alpha_set.append(field)
        #alpha_set.append("-%s"%field)
        for op in ops_set:
 
            if op == "ts_percentage":
 
                #lpha_set += ts_comp_factory(op, field, "percentage", [0.2, 0.5, 0.8])
                alpha_set += ts_comp_factory(op, field, "percentage", [0.5])
 
 
            elif op == "ts_decay_exp_window":
 
                #alpha_set += ts_comp_factory(op, field, "factor", [0.2, 0.5, 0.8])
                alpha_set += ts_comp_factory(op, field, "factor", [0.5])
 
 
            elif op == "ts_moment":
 
                alpha_set += ts_comp_factory(op, field, "k", [2, 3, 4])
 
            elif op == "ts_entropy":
 
                #alpha_set += ts_comp_factory(op, field, "buckets", [5, 10, 15, 20])
                alpha_set += ts_comp_factory(op, field, "buckets", [10])
 
            elif op.startswith("ts_") or op == "inst_tvr":
 
                alpha_set += ts_factory(op, field)
 
            elif op.startswith("group_"):
 
                alpha_set += group_factory(op, field, "usa")
 
            elif op.startswith("vector"):
 
                alpha_set += vector_factory(op, field)
 
            elif op == "signed_power":
 
                alpha = "%s(%s, 2)"%(op, field)
                alpha_set.append(alpha)
 
            else:
                alpha = "%s(%s)"%(op, field)
                alpha_set.append(alpha)
 
    return alpha_set
    
def get_group_second_order_factory(first_order, group_ops, region, group_limit=None, core_groups_only=False):
    second_order = []
    for fo in first_order:
        for group_op in group_ops:
            second_order += group_factory(
                group_op,
                fo,
                region,
                group_limit=group_limit,
                core_groups_only=core_groups_only,
            )
    return second_order
 
def get_ts_second_order_factory(first_order, ts_ops):
    second_order = []
    for fo in first_order:
        for ts_op in ts_ops:
            second_order += ts_factory(ts_op, fo)
    return second_order
 
 
def get_data_fields_csv(filename, prefix):
    '''
    inputs: 
    CSV file with header 'field' 
    outputs:
    A list of string
    '''
    df = pd.read_csv(filename,header=0,encoding = 'unicode_escape')
    collection = []
    for _, row in df.iterrows():
        if row['field'].startswith(prefix):
            collection.append(row['field'])
 
    return collection
 
def ts_arith_factory(ts_op, arith_op, field):
    first_order = "%s(%s)"%(arith_op, field)
    second_order = ts_factory(ts_op, first_order)
    return second_order
 
def arith_ts_factory(arith_op, ts_op, field):
    second_order = []
    first_order = ts_factory(ts_op, field)
    for fo in first_order:
        second_order.append("%s(%s)"%(arith_op, fo))
    return second_order
 
def ts_group_factory(ts_op, group_op, field, region, group_limit=None, core_groups_only=False):
    second_order = []
    first_order = group_factory(group_op, field, region, group_limit=group_limit, core_groups_only=core_groups_only)
    for fo in first_order:
        second_order += ts_factory(ts_op, fo)
    return second_order
 
def group_ts_factory(group_op, ts_op, field, region, group_limit=None, core_groups_only=False):
    second_order = []
    first_order = ts_factory(ts_op, field)
    for fo in first_order:
        second_order += group_factory(group_op, fo, region, group_limit=group_limit, core_groups_only=core_groups_only)
    return second_order
 
def vector_factory(op, field):
    output = []
    vectors = ["cap"]
    
    for vector in vectors:
    
        alpha = "%s(%s, %s)"%(op, field, vector)
        output.append(alpha)
    
    return output
 
def trade_when_factory(op, field, region, include_region_events=True, max_events=None):
    output = []
    open_events = ["ts_arg_max(volume, 5) == 0", "ts_corr(close, volume, 20) < 0",
                   "ts_corr(close, volume, 5) < 0", "ts_mean(volume,10)>ts_mean(volume,60)",
                   "group_rank(ts_std_dev(returns,60), sector) > 0.7", "ts_zscore(returns,60) > 2",
                   "ts_arg_min(volume, 5) > 3",
                   "ts_std_dev(returns, 5) > ts_std_dev(returns, 20)",
                   "ts_arg_max(close, 5) == 0", "ts_arg_max(close, 20) == 0",
                   "ts_corr(close, volume, 5) > 0", "ts_corr(close, volume, 5) > 0.3", "ts_corr(close, volume, 5) > 0.5",
                   "ts_corr(close, volume, 20) > 0", "ts_corr(close, volume, 20) > 0.3", "ts_corr(close, volume, 20) > 0.5",
                   "ts_regression(returns, %s, 5, lag = 0, rettype = 2) > 0"%field,
                   "ts_regression(returns, %s, 20, lag = 0, rettype = 2) > 0"%field,
                   "ts_regression(returns, ts_step(20), 20, lag = 0, rettype = 2) > 0",
                   "ts_regression(returns, ts_step(5), 5, lag = 0, rettype = 2) > 0"]

    exit_events = ["abs(returns) > 0.1", "-1"]

    usa_events = ["rank(rp_css_business) > 0.8", "ts_rank(rp_css_business, 22) > 0.8", "rank(vec_avg(mws82_sentiment)) > 0.8",
                  "ts_rank(vec_avg(mws82_sentiment),22) > 0.8", "rank(vec_avg(nws48_ssc)) > 0.8",
                  "ts_rank(vec_avg(nws48_ssc),22) > 0.8", "rank(vec_avg(mws50_ssc)) > 0.8", "ts_rank(vec_avg(mws50_ssc),22) > 0.8",
                  "ts_rank(vec_sum(scl12_alltype_buzzvec),22) > 0.9", "pcr_oi_270 < 1", "pcr_oi_270 > 1",]

    asi_events = ["rank(vec_avg(mws38_score)) > 0.8", "ts_rank(vec_avg(mws38_score),22) > 0.8"]

    eur_events = ["rank(rp_css_business) > 0.8", "ts_rank(rp_css_business, 22) > 0.8",
                  "rank(vec_avg(oth429_research_reports_fundamental_keywords_4_method_2_pos)) > 0.8",
                  "ts_rank(vec_avg(oth429_research_reports_fundamental_keywords_4_method_2_pos),22) > 0.8",
                  "rank(vec_avg(mws84_sentiment)) > 0.8", "ts_rank(vec_avg(mws84_sentiment),22) > 0.8",
                  "rank(vec_avg(mws85_sentiment)) > 0.8", "ts_rank(vec_avg(mws85_sentiment),22) > 0.8",
                  "rank(mdl110_analyst_sentiment) > 0.8", "ts_rank(mdl110_analyst_sentiment, 22) > 0.8",
                  "rank(vec_avg(nws3_scores_posnormscr)) > 0.8",
                  "ts_rank(vec_avg(nws3_scores_posnormscr),22) > 0.8",
                  "rank(vec_avg(mws36_sentiment_words_positive)) > 0.8",
                  "ts_rank(vec_avg(mws36_sentiment_words_positive),22) > 0.8"]

    glb_events = ["rank(vec_avg(mdl109_news_sent_1m)) > 0.8",
                  "ts_rank(vec_avg(mdl109_news_sent_1m),22) > 0.8",
                  "rank(vec_avg(nws20_ssc)) > 0.8",
                  "ts_rank(vec_avg(nws20_ssc),22) > 0.8",
                  "vec_avg(nws20_ssc) > 0",
                  "rank(vec_avg(nws20_bee)) > 0.8",
                  "ts_rank(vec_avg(nws20_bee),22) > 0.8",
                  "rank(vec_avg(nws20_qmb)) > 0.8",
                  "ts_rank(vec_avg(nws20_qmb),22) > 0.8"]

    chn_events = ["rank(vec_avg(oth111_xueqiunaturaldaybasicdivisionstat_senti_conform)) > 0.8",
                  "ts_rank(vec_avg(oth111_xueqiunaturaldaybasicdivisionstat_senti_conform),22) > 0.8",
                  "rank(vec_avg(oth111_gubanaturaldaydevicedivisionstat_senti_conform)) > 0.8",
                  "ts_rank(vec_avg(oth111_gubanaturaldaydevicedivisionstat_senti_conform),22) > 0.8",
                  "rank(vec_avg(oth111_baragedivisionstat_regi_senti_conform)) > 0.8",
                  "ts_rank(vec_avg(oth111_baragedivisionstat_regi_senti_conform),22) > 0.8"]

    kor_events = ["rank(vec_avg(mdl110_analyst_sentiment)) > 0.8",
                  "ts_rank(vec_avg(mdl110_analyst_sentiment),22) > 0.8",
                  "rank(vec_avg(mws38_score)) > 0.8",
                  "ts_rank(vec_avg(mws38_score),22) > 0.8"]

    twn_events = ["rank(vec_avg(mdl109_news_sent_1m)) > 0.8",
                  "ts_rank(vec_avg(mdl109_news_sent_1m),22) > 0.8",
                  "rank(rp_ess_business) > 0.8",
                  "ts_rank(rp_ess_business,22) > 0.8"]

    if include_region_events:
        region_events = {
            "USA": usa_events,
            "ASI": asi_events,
            "EUR": eur_events,
            "GLB": glb_events,
            "CHN": chn_events,
            "KOR": kor_events,
            "TWN": twn_events,
        }.get(region.upper(), [])
        open_events += region_events

    open_events = list(dict.fromkeys(open_events))
    if max_events is not None:
        open_events = open_events[:max_events]

    for oe in open_events:
        for ee in exit_events:
            alpha = "%s(%s, %s, %s)"%(op, oe, field, ee)
            output.append(alpha)
    return output
 
def ts_factory(op, field):
    output = []
    #days = [3, 5, 10, 20, 60, 120, 240]
    days = [5, 22, 66, 120, 240]
    
    for day in days:
    
        alpha = "%s(%s, %d)"%(op, field, day)
        output.append(alpha)
    
    return output
 
def ts_comp_factory(op, field, factor, paras):
    output = []
    #l1, l2 = [3, 5, 10, 20, 60, 120, 240], paras
    l1, l2 = [5, 22, 66, 240], paras
    comb = list(product(l1, l2))
    
    for day,para in comb:
        
        if type(para) == float:
            alpha = "%s(%s, %d, %s=%.1f)"%(op, field, day, factor, para)
        elif type(para) == int:
            alpha = "%s(%s, %d, %s=%d)"%(op, field, day, factor, para)
            
        output.append(alpha)
    
    return output
 
def twin_field_factory(op, field, fields):
    
    output = []
    #days = [3, 5, 10, 20, 60, 120, 240]
    days = [5, 22, 66, 240]
    outset = list(set(fields) - set([field]))
    
    for day in days:
        for counterpart in outset:
            alpha = "%s(%s, %s, %d)"%(op, field, counterpart, day)
            output.append(alpha)
    
    return output
 
 
def group_factory(op, field, region, group_limit=None, core_groups_only=False):
    output = []
    vectors = ["cap"] 
    
    chn_group_13 = ['pv13_h_min2_sector', 'pv13_di_6l', 'pv13_rcsed_6l', 'pv13_di_5l', 'pv13_di_4l', 
                        'pv13_di_3l', 'pv13_di_2l', 'pv13_di_1l', 'pv13_parent', 'pv13_level']
    
    
    chn_group_1 = ['sta1_top3000c30','sta1_top3000c20','sta1_top3000c10','sta1_top3000c2','sta1_top3000c5']
    
    chn_group_2 = ['sta2_top3000_fact4_c10','sta2_top2000_fact4_c50','sta2_top3000_fact3_c20']
    
    hkg_group_13 = ['pv13_10_f3_g2_minvol_1m_sector', 'pv13_10_minvol_1m_sector', 'pv13_20_minvol_1m_sector', 
                    'pv13_2_minvol_1m_sector', 'pv13_5_minvol_1m_sector', 'pv13_1l_scibr', 'pv13_3l_scibr',
                    'pv13_2l_scibr', 'pv13_4l_scibr', 'pv13_5l_scibr']
    
    hkg_group_1 = ['sta1_allc50','sta1_allc5','sta1_allxjp_513_c20','sta1_top2000xjp_513_c5']
    
    hkg_group_2 = ['sta2_all_xjp_513_all_fact4_c10','sta2_top2000_xjp_513_top2000_fact3_c10',
                   'sta2_allfactor_xjp_513_13','sta2_top2000_xjp_513_top2000_fact3_c20']
    
    twn_group_13 = ['pv13_2_minvol_1m_sector','pv13_20_minvol_1m_sector','pv13_10_minvol_1m_sector',
                    'pv13_5_minvol_1m_sector','pv13_10_f3_g2_minvol_1m_sector','pv13_5_f3_g2_minvol_1m_sector',
                    'pv13_2_f4_g3_minvol_1m_sector']
    
    twn_group_1 = ['sta1_allc50','sta1_allxjp_513_c50','sta1_allxjp_513_c20','sta1_allxjp_513_c2',
                   'sta1_allc20','sta1_allxjp_513_c5','sta1_allxjp_513_c10','sta1_allc2','sta1_allc5']
    
    twn_group_2 = ['sta2_allfactor_xjp_513_0','sta2_all_xjp_513_all_fact3_c20',
                   'sta2_all_xjp_513_all_fact4_c20','sta2_all_xjp_513_all_fact4_c50']
    
    usa_group_13 = ['pv13_h_min2_3000_sector','pv13_r2_min20_3000_sector','pv13_r2_min2_3000_sector',
                    'pv13_r2_min2_3000_sector', 'pv13_h_min2_focused_pureplay_3000_sector']
    
    usa_group_1 = ['sta1_top3000c50','sta1_allc20','sta1_allc10','sta1_top3000c20','sta1_allc5']
    
    usa_group_2 = ['sta2_top3000_fact3_c50','sta2_top3000_fact4_c20','sta2_top3000_fact4_c10']
    
    usa_group_6 = ['mdl10_group_name']
    
    asi_group_13 = ['pv13_20_minvol_1m_sector', 'pv13_5_f3_g2_minvol_1m_sector', 'pv13_10_f3_g2_minvol_1m_sector',
                    'pv13_2_f4_g3_minvol_1m_sector', 'pv13_10_minvol_1m_sector', 'pv13_5_minvol_1m_sector']
    
    asi_group_1 = ['sta1_allc50', 'sta1_allc10', 'sta1_minvol1mc50','sta1_minvol1mc20',
                   'sta1_minvol1m_normc20', 'sta1_minvol1m_normc50']
    
    jpn_group_1 = ['sta1_alljpn_513_c5', 'sta1_alljpn_513_c50', 'sta1_alljpn_513_c2', 'sta1_alljpn_513_c20']
    
    jpn_group_2 = ['sta2_top2000_jpn_513_top2000_fact3_c20', 'sta2_all_jpn_513_all_fact1_c5',
                   'sta2_allfactor_jpn_513_9', 'sta2_all_jpn_513_all_fact1_c10']
    
    jpn_group_13 = ['pv13_2_minvol_1m_sector', 'pv13_2_f4_g3_minvol_1m_sector', 'pv13_10_minvol_1m_sector',
                    'pv13_10_f3_g2_minvol_1m_sector', 'pv13_all_delay_1_parent', 'pv13_all_delay_1_level']
    
    kor_group_13 = ['pv13_10_f3_g2_minvol_1m_sector', 'pv13_5_minvol_1m_sector', 'pv13_5_f3_g2_minvol_1m_sector',
                    'pv13_2_minvol_1m_sector', 'pv13_20_minvol_1m_sector', 'pv13_2_f4_g3_minvol_1m_sector']
    
    kor_group_1 = ['sta1_allc20','sta1_allc50','sta1_allc2','sta1_allc10','sta1_minvol1mc50',
                   'sta1_allxjp_513_c10', 'sta1_top2000xjp_513_c50']
    
    kor_group_2 =['sta2_all_xjp_513_all_fact1_c50','sta2_top2000_xjp_513_top2000_fact2_c50',
                  'sta2_all_xjp_513_all_fact4_c50','sta2_all_xjp_513_all_fact4_c5']
    
    eur_group_13 = ['pv13_5_sector', 'pv13_2_sector', 'pv13_v3_3l_scibr', 'pv13_v3_2l_scibr', 'pv13_2l_scibr',
                    'pv13_52_sector', 'pv13_v3_6l_scibr', 'pv13_v3_4l_scibr', 'pv13_v3_1l_scibr']
    
    eur_group_1 = ['sta1_allc10', 'sta1_allc2', 'sta1_top1200c2', 'sta1_allc20', 'sta1_top1200c10']
    
    eur_group_2 = ['sta2_top1200_fact3_c50','sta2_top1200_fact3_c20','sta2_top1200_fact4_c50']
    
    glb_group_13 = ["pv13_10_f2_g3_sector", "pv13_2_f3_g2_sector", "pv13_2_sector", "pv13_52_all_delay_1_sector"]
        
    glb_group_1 = ['sta1_allc20', 'sta1_allc10', 'sta1_allc50', 'sta1_allc5']
    
    glb_group_2 = ['sta2_all_fact4_c50', 'sta2_all_fact4_c20', 'sta2_all_fact3_c20', 'sta2_all_fact4_c10']
    
    glb_group_13 = ['pv13_2_sector', 'pv13_10_sector', 'pv13_3l_scibr', 'pv13_2l_scibr', 'pv13_1l_scibr',
                    'pv13_52_minvol_1m_all_delay_1_sector','pv13_52_minvol_1m_sector','pv13_52_minvol_1m_sector'] 
    
    amr_group_13 = ['pv13_4l_scibr', 'pv13_1l_scibr', 'pv13_hierarchy_min51_f1_sector',
                    'pv13_hierarchy_min2_600_sector', 'pv13_r2_min2_sector', 'pv13_h_min20_600_sector']
    
    bps_group = "bucket(rank(fnd28_value_05480), range='0.1, 1, 0.1')"
    pb_group = "bucket(rank(close/fnd28_value_05480), range='0.1, 1, 0.1')"
    cap_group = "bucket(rank(cap), range='0.1, 1, 0.1')"
    asset_group = "bucket(rank(assets),range='0.1, 1, 0.1')"
    sector_cap_group = "bucket(group_rank(cap, sector),range='0.1, 1, 0.1')"
    sector_asset_group = "bucket(group_rank(assets, sector),range='0.1, 1, 0.1')"

    vol_group = "bucket(rank(ts_std_dev(returns,20)),range = '0.1, 1, 0.1')"

    liquidity_group = "bucket(rank(close*volume),range = '0.1, 1, 0.1')"

    groups = ["market","sector", "industry", "subindustry",
              pb_group, bps_group, cap_group, asset_group, sector_cap_group, sector_asset_group, vol_group, liquidity_group]

    if core_groups_only:
        groups = ["market", "sector", "industry", "subindustry", cap_group, vol_group, liquidity_group]
    elif region == "CHN":
        groups += chn_group_13 + chn_group_1 + chn_group_2  
    if region == "TWN":
        groups += twn_group_13 + twn_group_1 + twn_group_2 
    if region == "ASI":
        groups += asi_group_13 + asi_group_1 
    if region == "USA":
        groups += usa_group_13 + usa_group_1 + usa_group_2  
    if region == "HKG":
        groups += hkg_group_13 + hkg_group_1 + hkg_group_2 
    if region == "KOR":
        groups += kor_group_13 + kor_group_1 + kor_group_2 
    if region == "EUR": 
        groups += eur_group_13 + eur_group_1 + eur_group_2 
    if region == "GLB":
        groups += glb_group_13 + glb_group_1 + glb_group_2
    if region == "AMR":
        groups += amr_group_13 
    if region == "JPN":
        groups += jpn_group_1 + jpn_group_2 + jpn_group_13 

    groups = list(dict.fromkeys(groups))
    if group_limit is not None:
        groups = groups[:group_limit]
        
    for group in groups:
        if op.startswith("group_vector"):
            for vector in vectors:
                alpha = "%s(%s,%s,densify(%s))"%(op, field, vector, group)
                output.append(alpha)
        elif op.startswith("group_percentage"):
            alpha = "%s(%s,densify(%s),percentage=0.5)"%(op, field, group)
            output.append(alpha)
        else:
            alpha = "%s(%s,densify(%s))"%(op, field, group)
            output.append(alpha)
        
    return output
