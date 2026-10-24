"""Host test workaround for restricted environments hiding child PIDs from psutil.
Does not change CWL scheduling, command execution, output validation or science.
Only unavailable memory telemetry falls back to Popen.wait().
Use ordinary cwltool on normal hosts.
"""
import sys,psutil
from cwltool.job import JobBase
from cwltool.main import main
original=JobBase.process_monitor
def monitor(self,process):
    try:return original(self,process)
    except psutil.NoSuchProcess:return process.wait()
JobBase.process_monitor=monitor
sys.exit(main())
