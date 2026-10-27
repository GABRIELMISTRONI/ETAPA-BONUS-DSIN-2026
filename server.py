from __future__ import annotations

import json
import math
import os
import queue
import random
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
VENDOR_PATH = ROOT / "vendor"
if VENDOR_PATH.is_dir():
    sys.path.insert(0, str(VENDOR_PATH))
DB_PATH = Path(os.environ.get("FOGO_DB", ROOT / "fogo.sqlite3"))
HOST, PORT = os.environ.get("FOGO_HOST", "127.0.0.1"), int(os.environ.get("FOGO_PORT", "8000"))
REGIONS = ["Centro", "Jardim Norte", "Vila Industrial", "Porto", "Alto da Serra", "Parque Sul", "Orla", "Distrito Leste"]
REGION_BY_NEIGHBORHOOD = {"Centro":"Central","Jardim Norte":"Norte","Vila Industrial":"Sul","Porto":"Leste","Alto da Serra":"Norte","Parque Sul":"Sul","Orla":"Leste","Distrito Leste":"Leste"}
ADMIN_REGIONS = sorted(set(REGION_BY_NEIGHBORHOOD.values()))
TYPES = ["Radar de velocidade", "Radar de semáforo", "Câmera de videomonitoramento", "Balança de caminhão", "Veículo autônomo de fiscalização", "Cancela automatizada", "Totem de estacionamento", "Patinete elétrico", "Viatura", "Moto de agente", "Táxi", "Mototáxi", "Transporte escolar", "Viatura da Guarda Municipal", "Viatura da Polícia Militar"]
STATUS = ["operacional", "mau funcionamento", "em manutenção", "desativado", "furtado", "não instalado"]
LOCAL_TZ = ZoneInfo("America/Fortaleza")
LOCK = threading.Lock()
SUBSCRIBERS: list[queue.Queue] = []


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def publish(event, payload):
    message = json.dumps({"event": event, "data": payload}, ensure_ascii=False)
    with LOCK:
        for q in list(SUBSCRIBERS):
            try:
                q.put_nowait(message)
            except queue.Full:
                pass


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS equipment(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL,
          serial TEXT NOT NULL UNIQUE, brand TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
          organization TEXT NOT NULL DEFAULT 'Trânsito', reference TEXT NOT NULL DEFAULT '',
          cep TEXT NOT NULL DEFAULT '', street TEXT NOT NULL DEFAULT '', number TEXT NOT NULL DEFAULT '',
          neighborhood TEXT NOT NULL, city TEXT NOT NULL DEFAULT 'Cidade-Modelo/PB',
          lat REAL NOT NULL, lng REAL NOT NULL, status TEXT NOT NULL, maintenance TEXT NOT NULL DEFAULT 'nenhuma',
          maintenance_date TEXT, fields_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agents(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, role TEXT NOT NULL, organization TEXT NOT NULL,
          registration TEXT NOT NULL UNIQUE, neighborhood TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
          status TEXT NOT NULL DEFAULT 'ativo', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telemetry(
          id INTEGER PRIMARY KEY AUTOINCREMENT, equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
          metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL DEFAULT '', recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS occurrences(
          id INTEGER PRIMARY KEY AUTOINCREMENT, neighborhood TEXT NOT NULL, category TEXT NOT NULL,
          occurred_at TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS maintenance(
          id INTEGER PRIMARY KEY AUTOINCREMENT, equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
          scheduled_for TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'agendada', notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS alerts(
          id INTEGER PRIMARY KEY AUTOINCREMENT, severity TEXT NOT NULL, title TEXT NOT NULL,
          detail TEXT NOT NULL, neighborhood TEXT NOT NULL, created_at TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS telemetry_equipment_time ON telemetry(equipment_id, recorded_at);
        CREATE INDEX IF NOT EXISTS occurrences_time ON occurrences(occurred_at);
        """)
        columns={r[1] for r in db.execute("PRAGMA table_info(equipment)")}
        if "organization" not in columns:
            db.execute("ALTER TABLE equipment ADD COLUMN organization TEXT NOT NULL DEFAULT 'Trânsito'")
        if "reference" not in columns:
            db.execute("ALTER TABLE equipment ADD COLUMN reference TEXT NOT NULL DEFAULT ''")
        if db.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 0:
            seed(db)


def seed(db):
    rng = random.Random(42)
    # Coordenadas demonstrativas em João Pessoa; bairros são setores esquemáticos para o MVP.
    centers = [( -7.119, -34.883),(-7.105,-34.866),(-7.135,-34.890),(-7.116,-34.852),(-7.093,-34.897),(-7.151,-34.872),(-7.115,-34.825),(-7.087,-34.850)]
    brands = ["Intelbras", "Hikvision", "Kapsch", "Toledo", "Siemens"]
    statuses = ["operacional"] * 31 + ["mau funcionamento"] * 5 + ["em manutenção"] * 4 + ["desativado"] * 3 + ["furtado"] * 1 + ["não instalado"] * 4
    rng.shuffle(statuses)
    stamp = now_iso()
    for i in range(48):
        region = REGIONS[i % len(REGIONS)]; lat, lng = centers[i % len(centers)]
        status = statuses[i]
        maintenance = "imediata" if status == "mau funcionamento" and i % 2 else ("agendada" if i % 4 == 0 else "nenhuma")
        due = (datetime.now(timezone.utc) + timedelta(days=(i % 12)-3)).date().isoformat() if maintenance == "agendada" else None
        fields = {"Velocidade máxima (km/h)": 40 + (i % 5)*10} if i % 10 == 0 else ({"Visão noturna": "Sim", "Resolução": "4 MP"} if i % 10 == 2 else {"Parâmetro": 10 + i % 90})
        equip_type=TYPES[i%10]
        org="Polícia Militar" if equip_type=="Viatura" and i%2 else "Guarda Municipal" if equip_type=="Viatura" else "SEMOB"
        db.execute("INSERT INTO equipment(name,type,serial,brand,model,organization,reference,cep,street,number,neighborhood,city,lat,lng,status,maintenance,maintenance_date,fields_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (f"{equip_type} {i+1:02}", equip_type, f"FG-{1000+i*7}", brands[i%5], f"M{100+i%9}", org, "Em frente ao Mercado do Tio" if i%11==0 else "", f"58000-{100+i:03}", f"Rua {i+10}", str(100+i), region, "João Pessoa/PB", lat+rng.uniform(-.004,.004), lng+rng.uniform(-.004,.004), status, maintenance, due, json.dumps(fields,ensure_ascii=False), stamp, stamp))
        eid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        for day in range(13,-1,-1):
            base = 68 + rng.random()*8 - ((13-day) * .8 if i % 9 == 0 else 0)
            db.execute("INSERT INTO telemetry(equipment_id,metric,value,unit,recorded_at) VALUES(?,?,?,?,?)", (eid,"saude",max(15,base),"%",(datetime.now(timezone.utc)-timedelta(days=day)).isoformat(timespec="seconds")))
        if maintenance == "agendada" and due:
            db.execute("INSERT INTO maintenance(equipment_id,scheduled_for,status,notes) VALUES(?,?,?,?)", (eid,due,"agendada","Revisão preventiva"))
    roles=["Agente de trânsito","Guarda municipal","Policial militar"]
    for i in range(14):
        region=REGIONS[i%8]; lat,lng=centers[i%8]
        db.execute("INSERT INTO agents(name,role,organization,registration,neighborhood,lat,lng,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (f"Agente {i+1:02}",roles[i%3],"Trânsito" if i%3==0 else "Segurança",f"M-{500+i}",region,lat+rng.uniform(-.003,.003),lng+rng.uniform(-.003,.003),"inativo" if i%5==4 else "ativo",stamp))
    # Histórico sintético com pico de fim de semana na Orla e pico noturno no Centro.
    for d in range(90, -1, -1):
        day=datetime.now(timezone.utc)-timedelta(days=d)
        for j,region in enumerate(REGIONS):
            count=2+(j*3+d%4)%5
            if j==6 and day.weekday()>=5: count+=5
            if j==0: count+=2
            for n in range(count):
                hour=rng.choices(range(24),weights=[1,1,1,1,1,2,3,5,4,3,3,3,4,3,3,4,5,7,9,8,6,4,3,2])[0]
                stamp2=(day.replace(hour=hour,minute=rng.randrange(60),second=0,microsecond=0)).isoformat(timespec="seconds")
                db.execute("INSERT INTO occurrences(neighborhood,category,occurred_at,description) VALUES(?,?,?,?)",(region,rng.choice(["trânsito","patrimônio","segurança"]),stamp2,"Ocorrência histórica simulada"))


def rowdict(row):
    if row is None: return None
    d=dict(row)
    if "fields_json" in d:
        d["fields"]=json.loads(d.pop("fields_json") or "{}")
    if "neighborhood" in d:
        d["region"]=REGION_BY_NEIGHBORHOOD.get(d["neighborhood"],"")
    return d


def state():
    with connect() as db:
        eq=[rowdict(r) for r in db.execute("SELECT * FROM equipment ORDER BY id")]
        agents=[rowdict(r) for r in db.execute("SELECT * FROM agents ORDER BY id")]
        alerts=[rowdict(r) for r in db.execute("SELECT * FROM alerts WHERE resolved=0 ORDER BY CASE severity WHEN 'critico' THEN 0 WHEN 'alto' THEN 1 ELSE 2 END,created_at DESC LIMIT 12")]
        occ=db.execute("SELECT COUNT(*) FROM occurrences WHERE occurred_at>=?",((datetime.now(timezone.utc)-timedelta(days=90)).isoformat(),)).fetchone()[0]
        return {"equipment":eq,"agents":agents,"alerts":alerts,"regions":ADMIN_REGIONS,"neighborhoods":REGIONS,"regionByNeighborhood":REGION_BY_NEIGHBORHOOD,"types":TYPES,"occurrences90d":occ,"serverTime":now_iso()}


def predictions():
    current=datetime.now(LOCAL_TZ)
    with connect() as db:
        rows=db.execute("SELECT neighborhood,occurred_at FROM occurrences WHERE occurred_at>=?",((current-timedelta(days=90)).isoformat(),)).fetchall()
        eq=db.execute("SELECT neighborhood,status,maintenance,maintenance_date FROM equipment WHERE status!='não instalado'").fetchall()
        data={}
        daily_counts={region:{} for region in REGIONS}
        today=current.date()
        for r in rows:
            dt=datetime.fromisoformat(r["occurred_at"]).astimezone(LOCAL_TZ)
            # Recência exponencial: ocorrências dos últimos 30 dias têm maior peso.
            weight=math.exp(-max(0,(current-dt).days)/35)
            key=(r["neighborhood"],dt.weekday(),dt.hour)
            data[key]=data.get(key,0)+weight
            age_hours=(current-dt).total_seconds()/3600
            days_ago=int(age_hours//24) if age_hours>=0 else -1
            if 0<=days_ago<=28:
                counts=daily_counts.setdefault(r["neighborhood"],{})
                counts[days_ago]=counts.get(days_ago,0)+1
        maxv=max(data.values(),default=1)
        byregion={}
        for region in REGIONS:
            items=[e for e in eq if e["neighborhood"]==region]
            count=max(1,len(items)); unavailable=sum(e["status"]!="operacional" for e in items)/count
            pending=sum(e["maintenance"]=="imediata" or (e["maintenance"]=="agendada" and e["maintenance_date"] and e["maintenance_date"]<=(current+timedelta(days=7)).date().isoformat()) for e in items)
            byregion[region]=[]
            for offset in range(24):
                forecast=current+timedelta(hours=offset)
                historic=max((data.get((region,forecast.weekday(),h),0) for h in ((forecast.hour-1)%24,forecast.hour,(forecast.hour+1)%24)),default=0)/maxv
                value=min(1,.65*historic+.20*unavailable+.15*min(1,pending/4))
                byregion[region].append(round(value,3))
        trend=[]
        for t in TYPES:
            latest=db.execute("SELECT e.id,AVG(CASE WHEN julianday('now')-julianday(recorded_at)<=3 THEN value END) a,AVG(CASE WHEN julianday('now')-julianday(recorded_at) BETWEEN 10 AND 14 THEN value END) b FROM equipment e LEFT JOIN telemetry t ON t.equipment_id=e.id WHERE e.type=? GROUP BY e.id",(t,)).fetchall()
            deltas=[(x["b"]-x["a"]) for x in latest if x["a"] is not None and x["b"] is not None]
            mean=sum(deltas)/len(deltas) if deltas else 0
            current_values=[x["a"] for x in latest if x["a"] is not None]
            projected=[max(0,min(100,x["a"]+(x["a"]-x["b"])*(7/10.5))) for x in latest if x["a"] is not None and x["b"] is not None]
            trend.append({"type":t,"delta":round(mean,1),"risk":"alto" if mean>12 else "moderado" if mean>5 else "baixo","sample":len(deltas),"currentHealth":round(sum(current_values)/len(current_values),1) if current_values else None,"projectedHealth7d":round(sum(projected)/len(projected),1) if projected else None})
        active_agents=db.execute("SELECT COUNT(*) FROM agents WHERE status='ativo'").fetchone()[0]
        statistical_anomalies=[]
        for neighborhood,counts in daily_counts.items():
            baseline=[counts.get(day,0) for day in range(1,29)]
            average=sum(baseline)/len(baseline)
            deviation=math.sqrt(sum((x-average)**2 for x in baseline)/len(baseline))
            observed=counts.get(0,0)
            threshold=max(average+2.5*deviation,average*1.5+2,3)
            if observed>=threshold:
                statistical_anomalies.append({"neighborhood":neighborhood,"region":REGION_BY_NEIGHBORHOOD[neighborhood],"observed24h":observed,"baselineDaily":round(average,2),"threshold":round(threshold,2)})
        agent_rows=state_agents()
        recommendations=[]
        for neighborhood,values in byregion.items():
            peak=max(values)
            if peak<.55: continue
            active=sum(a["neighborhood"]==neighborhood and a["status"]=="ativo" for a in agent_rows)
            suggested=max(2,math.ceil(peak*3))
            recommendations.append({"region":neighborhood,"administrativeRegion":REGION_BY_NEIGHBORHOOD[neighborhood],"activeAgents":active,"risk":peak,"peakHour":(current.hour+values.index(peak))%24,"minimumSuggestedAgents":suggested,"coverageStatus":"adequate" if active>=suggested else "below_suggested"})
        return {"hours":[(current.hour+i)%24 for i in range(24)],"riskByRegion":byregion,"failureTrend":trend,"statisticalAnomalies":statistical_anomalies,"recommendations":recommendations,
                "method":"Risco relativo = 65% histórico horário com decaimento de recência + 20% indisponibilidade local + 15% manutenções pendentes (janela de 7 dias). A projeção de saúde estende linearmente a variação entre as médias recente (3 dias) e anterior (10–14 dias) por mais 7 dias, limitada a 0–100. O sinal estatístico compara ocorrências das últimas 24h com 28 dias anteriores (limiar: média + 2,5 desvios-padrão e pelo menos 3 eventos). Cobertura sugerida = máximo entre 2 e teto(risco × 3) agentes ativos em setores acima de 55%; é regra demonstrativa, não escala operacional.","activeAgents":active_agents}


def state_agents():
    with connect() as db: return [dict(r) for r in db.execute("SELECT neighborhood,status FROM agents")]


def send_json(handler, payload, status=200):
    data=json.dumps(payload,ensure_ascii=False).encode()
    handler.send_response(status); handler.send_header("Content-Type","application/json; charset=utf-8"); handler.send_header("Content-Length",str(len(data))); handler.send_header("Access-Control-Allow-Origin","*"); handler.end_headers(); handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Methods","GET,POST,PUT,DELETE,OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.end_headers()
    def body(self):
        n=int(self.headers.get("Content-Length",0)); return json.loads(self.rfile.read(n) or b"{}")
    def do_GET(self):
        p=urlparse(self.path); path=p.path
        if path=="/":
            f=ROOT/"static"/"index.html"; data=f.read_bytes(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path.startswith("/static/"):
            static_root=(ROOT/"static").resolve()
            f=(ROOT/path.lstrip("/")).resolve()
            if static_root not in f.parents or not f.is_file(): self.send_error(404); return
            data=f.read_bytes(); self.send_response(200); self.send_header("Content-Type","text/css; charset=utf-8" if f.suffix==".css" else "text/javascript; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path=="/api/state": return send_json(self,state())
        if path=="/api/predictions": return send_json(self,predictions())
        if path=="/api/cep":
            cep="".join(c for c in parse_qs(p.query).get("cep",[""])[0] if c.isdigit())
            if len(cep)!=8: return send_json(self,{"error":"CEP deve conter 8 dígitos."},400)
            try:
                from urllib.request import urlopen
                with urlopen(f"https://viacep.com.br/ws/{cep}/json/",timeout=5) as response: data=json.loads(response.read())
                if data.get("erro"): return send_json(self,{"error":"CEP não encontrado."},404)
                return send_json(self,data)
            except Exception: return send_json(self,{"error":"ViaCEP indisponível. Preencha o endereço manualmente."},503)
        if path=="/api/events":
            q=queue.Queue(maxsize=50)
            with LOCK: SUBSCRIBERS.append(q)
            self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.send_header("Cache-Control","no-cache"); self.send_header("Connection","keep-alive"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
            try:
                self.wfile.write(b"event: connected\ndata: {}\n\n"); self.wfile.flush()
                while True:
                    try: msg=q.get(timeout=20); self.wfile.write(("data: "+msg+"\n\n").encode())
                    except queue.Empty: self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError): pass
            finally:
                with LOCK:
                    if q in SUBSCRIBERS: SUBSCRIBERS.remove(q)
            return
        self.send_error(404)
    def do_POST(self):
        path=urlparse(self.path).path
        try: data=self.body()
        except Exception: return send_json(self,{"error":"JSON inválido."},400)
        if not isinstance(data,dict): return send_json(self,{"error":"O corpo da solicitação deve ser um objeto JSON."},400)
        if path=="/api/equipment": return self.save_equipment(data)
        if path=="/api/agents": return self.save_agent(data)
        if path=="/api/simulate": return send_json(self,simulate())
        if path=="/api/maintenance":
            try:
                equipment_id=int(data["equipment_id"])
                scheduled_for=date.fromisoformat(str(data["scheduled_for"])).isoformat()
                with connect() as db:
                    cur=db.execute("UPDATE equipment SET maintenance='agendada',maintenance_date=?,updated_at=? WHERE id=?",(scheduled_for,now_iso(),equipment_id))
                    if not cur.rowcount: return send_json(self,{"error":"Equipamento não encontrado."},404)
                    db.execute("INSERT INTO maintenance(equipment_id,scheduled_for,status,notes) VALUES(?,?,?,?)",(equipment_id,scheduled_for,"agendada",data.get("notes","")))
                publish("refresh",{"kind":"maintenance"}); return send_json(self,{"ok":True})
            except (KeyError,ValueError,TypeError,sqlite3.IntegrityError): return send_json(self,{"error":"Equipamento ou data de manutenção inválidos."},400)
        if path=="/api/occurrences":
            region=data.get("neighborhood")
            if region not in REGIONS: return send_json(self,{"error":"Bairro inválido ou ausente."},400)
            with connect() as db: db.execute("INSERT INTO occurrences(neighborhood,category,occurred_at,description) VALUES(?,?,?,?)",(region,str(data.get("category","segurança"))[:80],now_iso(),str(data.get("description","Ocorrência registrada"))[:500]))
            publish("refresh",{"kind":"occurrence"}); return send_json(self,{"ok":True},201)
        self.send_error(404)
    def do_PUT(self):
        path=urlparse(self.path).path
        try: data=self.body(); ident=int(path.rsplit("/",1)[1])
        except Exception: return send_json(self,{"error":"Dados inválidos."},400)
        if not isinstance(data,dict): return send_json(self,{"error":"O corpo da solicitação deve ser um objeto JSON."},400)
        if "/api/equipment/" in path: return self.save_equipment(data,ident)
        if "/api/agents/" in path: return self.save_agent(data,ident)
        self.send_error(404)
    def do_DELETE(self):
        path=urlparse(self.path).path
        try: ident=int(path.rsplit("/",1)[1])
        except Exception: return send_json(self,{"error":"ID inválido."},400)
        table="equipment" if "/api/equipment/" in path else "agents" if "/api/agents/" in path else None
        if not table: return self.send_error(404)
        with connect() as db: cur=db.execute(f"DELETE FROM {table} WHERE id=?",(ident,))
        if not cur.rowcount: return send_json(self,{"error":"Registro não encontrado."},404)
        publish("refresh",{"kind":table}); return send_json(self,{"ok":True})
    def save_equipment(self,d,ident=None):
        required=["name","type","serial","neighborhood","lat","lng","status"]
        if any(not str(d.get(k," ")).strip() for k in required): return send_json(self,{"error":"Preencha nome, tipo, série, bairro, coordenadas e situação."},400)
        if d["type"] not in TYPES or d["status"] not in STATUS or d["neighborhood"] not in REGIONS: return send_json(self,{"error":"Tipo, situação ou bairro inválido."},400)
        if d.get("region") and d["region"]!=REGION_BY_NEIGHBORHOOD[d["neighborhood"]]: return send_json(self,{"error":"A região não corresponde ao bairro selecionado."},400)
        if d.get("maintenance","nenhuma") not in ["nenhuma","agendada","imediata"]: return send_json(self,{"error":"Situação de manutenção inválida."},400)
        try:
            lat,lng=float(d["lat"]),float(d["lng"])
            if not (-90<=lat<=90 and -180<=lng<=180): raise ValueError
            if d.get("maintenance_date"): date.fromisoformat(str(d["maintenance_date"]))
        except (ValueError,TypeError): return send_json(self,{"error":"Coordenadas ou data de manutenção inválidas."},400)
        if not isinstance(d.get("fields",{}),dict): return send_json(self,{"error":"Os campos específicos devem ser um objeto JSON."},400)
        fields=(str(d.get("name","")),str(d["type"]),str(d["serial"]),str(d.get("brand","")),str(d.get("model","")),str(d.get("organization","Trânsito")),str(d.get("reference","")),str(d.get("cep","")),str(d.get("street","")),str(d.get("number","")),str(d["neighborhood"]),str(d.get("city","João Pessoa/PB")),lat,lng,d["status"],str(d.get("maintenance","nenhuma")),d.get("maintenance_date"),json.dumps(d.get("fields",{}),ensure_ascii=False),now_iso())
        try:
            with connect() as db:
                if ident:
                    db.execute("UPDATE equipment SET name=?,type=?,serial=?,brand=?,model=?,organization=?,reference=?,cep=?,street=?,number=?,neighborhood=?,city=?,lat=?,lng=?,status=?,maintenance=?,maintenance_date=?,fields_json=?,updated_at=? WHERE id=?",fields+(ident,))
                else:
                    db.execute("INSERT INTO equipment(name,type,serial,brand,model,organization,reference,cep,street,number,neighborhood,city,lat,lng,status,maintenance,maintenance_date,fields_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",fields[:18]+(now_iso(),fields[-1]))
            publish("refresh",{"kind":"equipment"}); return send_json(self,{"ok":True},201 if not ident else 200)
        except sqlite3.IntegrityError: return send_json(self,{"error":"Número de série já cadastrado."},409)
        except (ValueError,TypeError): return send_json(self,{"error":"Coordenadas inválidas."},400)
    def save_agent(self,d,ident=None):
        required=["name","role","registration","neighborhood","lat","lng","status"]
        if any(not str(d.get(k," ")).strip() for k in required): return send_json(self,{"error":"Preencha nome, função, matrícula, bairro, coordenadas e situação."},400)
        if d["neighborhood"] not in REGIONS or d["status"] not in ["ativo","inativo"]: return send_json(self,{"error":"Bairro ou situação inválidos."},400)
        if d.get("region") and d["region"]!=REGION_BY_NEIGHBORHOOD[d["neighborhood"]]: return send_json(self,{"error":"A região não corresponde ao bairro selecionado."},400)
        try:
            lat,lng=float(d["lat"]),float(d["lng"])
            if not (-90<=lat<=90 and -180<=lng<=180): raise ValueError
        except (ValueError,TypeError): return send_json(self,{"error":"Coordenadas inválidas."},400)
        fields=(str(d["name"]),str(d["role"]),str(d.get("organization","Segurança")),str(d["registration"]),str(d["neighborhood"]),lat,lng,d["status"],now_iso())
        try:
            with connect() as db:
                if ident: db.execute("UPDATE agents SET name=?,role=?,organization=?,registration=?,neighborhood=?,lat=?,lng=?,status=?,updated_at=? WHERE id=?",fields+(ident,))
                else: db.execute("INSERT INTO agents(name,role,organization,registration,neighborhood,lat,lng,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",fields)
            publish("refresh",{"kind":"agent"}); return send_json(self,{"ok":True},201 if not ident else 200)
        except sqlite3.IntegrityError: return send_json(self,{"error":"Matrícula já cadastrada."},409)
        except (ValueError,TypeError): return send_json(self,{"error":"Coordenadas inválidas."},400)


def simulate():
    rng=random.Random()
    with connect() as db:
        equipment=db.execute("SELECT * FROM equipment WHERE status!='não instalado'").fetchall()
        if not equipment: return {"ok":True,"message":"Nenhum equipamento instalado para simular."}
        e=rng.choice(equipment); old=e["status"]
        metric="saude"; value=max(5,min(100,75+rng.gauss(0,13)))
        if rng.random()<.13: value=rng.uniform(10,35)
        db.execute("INSERT INTO telemetry(equipment_id,metric,value,unit,recorded_at) VALUES(?,?,?,?,?)",(e["id"],metric,value,"%",now_iso()))
        new=old
        stolen=rng.random()<.025 and old=="operacional"
        if stolen: new="furtado"
        elif value<28 and old=="operacional": new="mau funcionamento"
        elif old in ["mau funcionamento","em manutenção"] and rng.random()<.3: new="operacional"
        recovered=new=="operacional" and old in ["mau funcionamento","em manutenção"]
        if new!=old:
            if recovered and e["maintenance"]=="imediata":
                db.execute("UPDATE equipment SET status=?,maintenance='nenhuma',maintenance_date=NULL,updated_at=? WHERE id=?",(new,now_iso(),e["id"]))
                db.execute("UPDATE alerts SET resolved=1 WHERE title LIKE ? AND resolved=0",(f"%{e['serial']}%",))
            else:
                db.execute("UPDATE equipment SET status=?,updated_at=? WHERE id=?",(new,now_iso(),e["id"]))
        sev="critico" if new=="furtado" else "alto" if new=="mau funcionamento" or value<25 else "info"
        title=f"{e['type']} {e['serial']} — {'furto detectado' if new=='furtado' else 'falha provável' if value<30 else 'telemetria recebida'}"
        detail=f"Saúde medida: {value:.0f}%. Situação: {old} → {new}."
        db.execute("INSERT INTO alerts(severity,title,detail,neighborhood,created_at) VALUES(?,?,?,?,?)",(sev,title,detail,e["neighborhood"],now_iso()))
        if stolen:
            db.execute("INSERT INTO occurrences(neighborhood,category,occurred_at,description) VALUES(?,?,?,?)",(e["neighborhood"],"patrimônio",now_iso(),f"Furto simulado do equipamento {e['serial']}"))
        elif rng.random()<.12:
            category=rng.choice(["trânsito","patrimônio","segurança"])
            db.execute("INSERT INTO occurrences(neighborhood,category,occurred_at,description) VALUES(?,?,?,?)",(e["neighborhood"],category,now_iso(),"Ocorrência gerada pelo simulador IoT"))
        # Posição de agentes muda gradualmente, preservando o bairro vinculado.
        a=db.execute("SELECT * FROM agents WHERE status='ativo' ORDER BY RANDOM() LIMIT 1").fetchone()
        if a:
            lat=float(a["lat"])+rng.uniform(-.001,.001); lng=float(a["lng"])+rng.uniform(-.001,.001)
            db.execute("UPDATE agents SET lat=?,lng=?,updated_at=? WHERE id=?",(lat,lng,now_iso(),a["id"]))
        event={"equipmentId":e["id"],"type":e["type"],"serial":e["serial"],"neighborhood":e["neighborhood"],"value":round(value,1),"status":new,"severity":sev,"title":title,"detail":detail}
    publish("telemetry",event); publish("refresh",{"kind":"simulation"})
    return {"ok":True,"event":event}


if __name__=="__main__":
    init_db()
    print(f"F.O.G.O. disponível em http://{HOST}:{PORT} (execute simulador.py em outro terminal para telemetria automática)",flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
