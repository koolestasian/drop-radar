# Smoke test for T20-agent-automation-research-findings.md. Run: CRASH=1 python t20-dbos-crash-smoke.py; then python t20-dbos-crash-smoke.py (needs `pip install dbos`; writes files in the cwd).
import os,sys,sqlite3
from dbos import DBOS, SetWorkflowID
DB="sqlite:///"+os.path.abspath("dbos_crash.sqlite")
DBOS(config={"name":"crashtest","system_database_url":DB,"run_admin_server":False})
SEND=os.path.abspath("sent.log")
@DBOS.step()
def draft(): print("step draft",flush=True); return "hello"
@DBOS.step()
def send(body):
    with open(SEND,"a") as f: f.write("SENT "+body+"\n")   # side effect
    print("step send",flush=True); return True
@DBOS.step()
def calendar(): 
    if os.environ.get("CRASH")=="1": print("CRASH before calendar",flush=True); os._exit(9)
    print("step calendar",flush=True)
@DBOS.workflow()
def loop(): b=draft(); send(b); calendar(); return "done"
if __name__=="__main__":
    DBOS.launch()
    with SetWorkflowID("wf-1"):
        print("result:", loop())
