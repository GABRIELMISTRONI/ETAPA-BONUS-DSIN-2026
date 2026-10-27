"""Simulador IoT independente: envia uma leitura sintetizada ao F.O.G.O."""
import argparse
import json
import time
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


def main():
    parser=argparse.ArgumentParser(description="Gera telemetria de demonstração para o F.O.G.O.")
    parser.add_argument("--url",default="http://127.0.0.1:8000",help="URL do servidor F.O.G.O.")
    parser.add_argument("--interval",type=int,default=25,help="Intervalo entre leituras, em segundos (mínimo 3)")
    args=parser.parse_args(); interval=max(3,args.interval); endpoint=args.url.rstrip("/")+"/api/simulate"
    print(f"Simulador ativo: {endpoint} · intervalo {interval}s. Ctrl+C encerra.",flush=True)
    while True:
        try:
            req=Request(endpoint,data=b"{}",headers={"Content-Type":"application/json"},method="POST")
            with urlopen(req,timeout=8) as response: event=json.loads(response.read())
            info=event.get("event",{})
            print(f"{info.get('serial','—')} · {info.get('neighborhood','—')} · saúde {info.get('value','—')}% · {info.get('status','—')}",flush=True)
        except (URLError,HTTPError,TimeoutError) as exc:
            print(f"Servidor indisponível: {exc}",flush=True)
        time.sleep(interval)


if __name__=="__main__": main()
