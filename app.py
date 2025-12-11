import os
from datetime import datetime

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

TSA_BASE_URL = "https://apps.tsa.dhs.gov/MyTSAWebService/GetTSOWaitTimes.ashx"


def map_tsa_wait_code(code):
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None, None

    if c == 0:
        return 0, 0

    low = (c - 1) * 10 + 1
    high = c * 10
    return low, high


@app.route("/api/tsa-wait-times")
def get_tsa_wait_times():
    airport = request.args.get("airport", "").upper().strip()
    if not airport or len(airport) != 3:
        return jsonify({"error": "airport parameter (3-letter code) is required"}), 400

    try:
        resp = requests.get(
            TSA_BASE_URL,
            params={"ap": airport, "output": "json"},
            timeout=8,
        )
        resp.raise_for_status()
        tsa_data = resp.json()
    except Exception as e:
        return jsonify({"error": f"Failed to reach TSA API: {e}"}), 502

    items = tsa_data if isinstance(tsa_data, list) else tsa_data.get("WaitTimes", [])

    lanes_map = {}

    for item in items:
        cp_index = str(item.get("CheckpointIndex", "Unknown"))
        airport_code = item.get("AirportCode", airport)
        wait_code = item.get("WaitTime")
        created = item.get("Created_Datetime")

        key = f"{airport_code}-CP-{cp_index}"
        min_wait, max_wait = map_tsa_wait_code(wait_code)

        lane = lanes_map.setdefault(
            key,
            {
                "name": f"Checkpoint {cp_index}",
                "waitSamples": [],
                "createdSamples": [],
            },
        )

        if min_wait is not None:
            lane["waitSamples"].append((min_wait, max_wait))
        if created:
            lane["createdSamples"].append(created)

    lanes = []
    for lane in lanes_map.values():
        if lane["waitSamples"]:
            mins = [m for (m, _) in lane["waitSamples"]]
            maxs = [M for (_, M) in lane["waitSamples"]]
            wait_min = min(mins)
            wait_max = max(maxs)
        else:
            wait_min = wait_max = None

        if wait_max is None:
            status = "UNKNOWN"
        elif wait_max <= 10:
            status = "NORMAL"
        elif wait_max <= 30:
            status = "BUSY"
        else:
            status = "VERY BUSY"

        latest_ts = max(lane["createdSamples"]) if lane["createdSamples"] else None

        lanes.append(
            {
                "name": lane["name"],
                "waitMin": wait_min,
                "waitMax": wait_max,
                "status": status,
                "precheck": False,
                "notes": None,
                "lastReportedAtRaw": latest_ts,
            }
        )

    return jsonify(
        {
            "airport": airport,
            "updatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "lanes": lanes,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
