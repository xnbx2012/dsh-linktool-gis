"""Reuse ArcPy initialization; each request executes the existing generated script.

Fresh Python globals and ResetEnvironments isolate requests. Startup and job
timeouts kill this worker and permit a later clean restart. No model or answer
logic is implemented here.
"""
import atexit,io,json,os,queue,subprocess,sys,threading,time
from pathlib import Path

class ArcPyWorker:
    def __init__(self,executable):
        self.executable=executable;self.process=None;self.replies=None;self.lock=threading.Lock();self.stderr=[];self.completed=0
        atexit.register(self.close)
    def close(self):
        p=self.process;self.process=None
        if p is not None:
            try:p.kill();p.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired):pass
    def _start(self,deadline):
        errors=[];began=time.monotonic();attempts=0
        for attempts in range(1,4):
            remaining=deadline-time.monotonic()
            if remaining<=0:break
            self.replies=queue.Queue();self.stderr=[];self.completed=0
            env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1','PYTHONUNBUFFERED':'1'}
            p=subprocess.Popen([self.executable,'-u',str(Path(__file__).resolve()),'--worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',errors='replace',env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            self.process=p;responses=self.replies;stderr=self.stderr
            def receive():
                try:
                    for line in p.stdout:
                        try:value=json.loads(line)
                        except ValueError:stderr.append(line[-2000:]);continue
                        if isinstance(value,dict) and value.get('_arcpy_protocol')==1:responses.put(value)
                        else:stderr.append(line[-2000:])
                finally:responses.put({'_closed':True})
            def errors_reader():
                for line in p.stderr:
                    stderr.append(line[-2000:])
                    if len(stderr)>50:del stderr[:25]
            threading.Thread(target=receive,daemon=True).start();threading.Thread(target=errors_reader,daemon=True).start()
            try:
                ready=responses.get(timeout=min(60,remaining))
                if ready.get('ready'):
                    return {'startup_attempts':attempts,'startup_seconds':time.monotonic()-began,'startup_errors':errors,'worker_pid':p.pid}
                raise RuntimeError('ArcPy worker exited during initialization: '+''.join(stderr)[-1000:])
            except (queue.Empty,RuntimeError) as ex:
                errors.append(str(ex) or 'ArcPy import exceeded startup watchdog (60 seconds)');self.close()
        raise TimeoutError('ArcPy worker startup failed: '+'; '.join(errors))
    def run(self,script,input_data,timeout):
        with self.lock:
            started=time.monotonic();deadline=started+timeout;warm=self.process is not None and self.process.poll() is None
            diagnostics={'worker_reused':warm,'startup_attempts':0,'startup_seconds':0}
            try:
                if not warm:diagnostics.update(self._start(deadline))
                diagnostics['worker_pid']=self.process.pid
                self.process.stdin.write(json.dumps({'script':script,'input':input_data},ensure_ascii=True)+'\n');self.process.stdin.flush()
                result=self.replies.get(timeout=max(.01,deadline-time.monotonic()))
                if result.get('_closed'):raise RuntimeError('ArcPy worker terminated: '+''.join(self.stderr)[-1000:])
                diagnostics.update({'elapsed_seconds':time.monotonic()-started,'script_seconds':result.get('script_seconds'),'worker_request_index':self.completed+1});self.completed+=1
                result['execution_diagnostics']=diagnostics;return result
            except (queue.Empty,TimeoutError,RuntimeError,OSError) as ex:
                self.close();return {'returncode':1,'stdout':'','stderr':str(ex) or f'ArcPy request timed out after {timeout} seconds','execution_diagnostics':{**diagnostics,'elapsed_seconds':time.monotonic()-started,'worker_killed':True}}

def serve():
    protocol_in=sys.stdin;protocol_out=sys.stdout
    import arcpy
    defaults={}
    for name in arcpy.ListEnvironments():
        try:defaults[name]=getattr(arcpy.env,name)
        except (AttributeError,RuntimeError):pass
    print(json.dumps({'_arcpy_protocol':1,'ready':True,'pid':os.getpid()}),file=protocol_out,flush=True)
    for line in protocol_in:
        request=json.loads(line);out=io.StringIO();err=io.StringIO();original_in=sys.stdin;original_out=sys.stdout;original_err=sys.stderr;started=time.monotonic();code=0
        try:
            sys.stdin=io.StringIO(json.dumps(request.get('input'),ensure_ascii=False));sys.stdout=out;sys.stderr=err
            arcpy.ResetEnvironments()
            # Some ArcGIS builds retain overwriteOutput after ResetEnvironments.
            # Restore the actual cold-start values explicitly, including workspace.
            for name,value in defaults.items():
                try:setattr(arcpy.env,name,value)
                except (AttributeError,RuntimeError):pass
            exec(compile(request['script'],'<arcpy-mcp-script>','exec'),{'__name__':'__main__'})
        except SystemExit as ex:code=ex.code if isinstance(ex.code,int) else (1 if ex.code else 0)
        except BaseException:
            import traceback
            traceback.print_exc(file=err);code=1
        finally:
            sys.stdin=original_in;sys.stdout=original_out;sys.stderr=original_err
        print(json.dumps({'_arcpy_protocol':1,'returncode':code,'stdout':out.getvalue(),'stderr':err.getvalue(),'script_seconds':time.monotonic()-started},ensure_ascii=True),file=protocol_out,flush=True)

if __name__=='__main__' and '--worker' in sys.argv:serve()
