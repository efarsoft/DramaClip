import sys, sqlite3, shutil, tempfile, pathlib, subprocess
sys.path.insert(0, 'service')
from tests.api.test_produce import Harness
from dramaclip.transport.rpc import RpcRequest
from dramaclip.infra.ffmpeg.binaries import resolve_ffmpeg

tmp = pathlib.Path(tempfile.mkdtemp())
sample = tmp / 'media' / 'ep1.mp4'
sample.parent.mkdir(parents=True, exist_ok=True)
subprocess.run([resolve_ffmpeg(), '-y', '-f', 'lavfi', '-i', 'testsrc2=duration=3:size=320x640:rate=15', '-pix_fmt', 'yuv420p', str(sample)], check=True, capture_output=True)

from dramaclip.infra.storage import db as dbmod
memory = dbmod.connect(':memory:')
dbmod.migrate(memory)
h = Harness(memory, tmp / 'cache')
h.rpc('project.create', {'name': '调试', 'source_path': str(tmp / 'media')})
pid = h.rpc('project.list')[0]['id']
h.rpc('project.scan_episodes', {'project_id': pid})
h.wait_job(str(h.rpc('analysis.start', {'project_id': pid})['job_id']))
from dramaclip.transport.rpc import RpcRequest as Req
resp = Router = None
from dramaclip.transport.rpc import Router
resp = Router().dispatch(Req(id=9, method='narration.produce', params={'project_id': pid, 'modes': ['raw_clip']}))
if resp.error is not None:
    print('produce ERROR:', resp.error.code, resp.error.message)
else:
    st = h.wait_job(str(resp.result['job_id']))
    print('produce:', st['status'], '| error:', st.get('error'))
    exports = h.rpc('export.list', {'project_id': pid})
    print('exports:', [(e['narration_mode'], e['status']) for e in exports])
