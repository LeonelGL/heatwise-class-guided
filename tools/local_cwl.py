"""Generate a host-only CWL variant for testing without Docker.
Never claim that this validates container execution.
"""
from pathlib import Path
import yaml
r=Path(__file__).resolve().parents[1];out=r/'cwl/local';out.mkdir(exist_ok=True)
for p in (r/'cwl').glob('*.cwl'):
    d=yaml.safe_load(p.read_text())
    d.get('requirements',{}).pop('DockerRequirement',None)
    for i in d.get('inputs',[]):
        default=i.get('default')
        if isinstance(default,dict) and 'location' in default:default['location']='../'+default['location']
    (out/p.name).write_text(yaml.safe_dump(d,sort_keys=False))
