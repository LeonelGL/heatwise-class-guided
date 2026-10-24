"""Compare a completed real Sepolia experiment with the report; no pipeline inputs."""
import argparse,json
import numpy as np
REFERENCE=np.array([.467,.518,.560,.602,.661,.704,.763,.940,.982,2.002,2.188,2.239,2.281,2.382,2.441])
p=argparse.ArgumentParser();p.add_argument('selected_bands');a=p.parse_args()
got=np.asarray(json.load(open(a.selected_bands))['wavelengths_um'])
print(json.dumps({'reference_only':True,'reference_um':REFERENCE.tolist(),'actual_um':got.tolist(),'matches_at_report_precision':bool(len(got)==len(REFERENCE) and np.allclose(got,REFERENCE,rtol=0,atol=.0005))},indent=2))
