import httpx, json, sys, io
import pandas as pd
S = sys.argv[1]  # directory with stress.csv and synth/scenario_000
B = "http://127.0.0.1:8001"
c = httpx.Client(timeout=300, trust_env=False)
r = c.post(B + "/api/v1/auth/register", json={"email": "e2e@example.com", "password": "longpassword1", "name": "E2E", "business_name": "E2E Co"})
if r.status_code == 409:
    r = c.post(B + "/api/v1/auth/login", json={"email": "e2e@example.com", "password": "longpassword1"})
tok = r.json()["access_token"]; H = {"Authorization": "Bearer " + tok}
print("plant", c.post(B + "/api/v1/plants", headers=H, json={"plant_id": "demo", "name": "Demo Plant", "capacity_kw": 500}).status_code)
def upload(name, content, extra=None):
    files = {"file": (name, content)}
    files.update(extra or {})
    r = c.post(B + "/api/v1/analyze/upload", headers=H, files=files, data={"plant_id": "demo", "mode": "auto"})
    print(name, r.status_code)
    if r.status_code != 200: print(r.text); return None
    j = r.json(); ml = j["ml_analysis"]
    print("  ml_status", ml["analysis_status"], "| exp_dev", ml.get("expected_deviation_kwh"), "| model", j["model"])
    print("  summary:", j["analysis"]["summary"][:200]); print("  obs:", j["analysis"]["observations"]); print("  causes:", j["analysis"]["possible_causes"], "conf", j["analysis"]["confidence"]); print("  lim tail:", j["analysis"]["limitations"][-2:])
    return j
csv = open(S + "/stress.csv", "rb").read()
a = upload("e2e_operating_enriched.csv", csv)
df = pd.read_csv(S + "/stress.csv"); buf = io.BytesIO(); df.to_excel(buf, index=False)
b = upload("e2e_operating_enriched.xlsx", buf.getvalue())
d = S + "/synth/scenario_000/"
f = upload("operating_data.csv", open(d + "operating_data.csv", "rb").read(), {"weather_file": ("weather.csv", open(d + "weather.csv", "rb").read()), "forecast_file": ("forecast.csv", open(d + "forecast.csv", "rb").read()), "devices_file": ("devices.csv", open(d + "devices.csv", "rb").read())})
hist = c.get(B + "/api/v1/analyses?plant_id=demo", headers=H).json(); print("history total", hist["total"])
det = c.get(B + "/api/v1/analyses/" + a["request_id"], headers=H).json()
print("persisted matches upload:", det["result"] == a)
q = c.post(B + f"/api/v1/analyses/{a['request_id']}/chat/stream", headers=H, json={"question": "Why is measured output below expected energy?"})
print("stream", q.status_code, q.headers.get("content-type"), q.text.count("event: delta"), "deltas;", "done" in q.text)
q2 = c.post(B + f"/api/v1/analyses/{a['request_id']}/chat", headers=H, json={"question": "What should I check first?"}).json()
print("chat2 model", q2["model"], q2["answer"]["summary"][:150])
msgs = c.get(B + f"/api/v1/analyses/{a['request_id']}/chat", headers=H).json()["messages"]; print("messages", len(msgs), [m["role"] for m in msgs])
