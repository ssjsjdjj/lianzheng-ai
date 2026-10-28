"""LOCAL TEST DOUBLE ONLY. Not a model, not evidence of real inference."""
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if payload.get('model')=='reject-test-model':
            self.send_response(401);self.end_headers();self.wfile.write(b'provider error');return
        if payload.get('max_tokens')==128:
            content={'ok':True}
        else:
            context=json.loads(payload['messages'][-1]['content'])
            evidence=context['evidence'][0]
            quote=evidence['text'][:100]
            if '__BAD_QUOTE__' in context['question']:quote='This quote does not exist in any source document.'
            content={'claims':[{'text':'请结合当前证据核对依赖路径，并执行项目回归测试；文档不能替代兼容性验证。',
                                'evidence_ids':[evidence['id']],'quotes':[{'evidence_id':evidence['id'],'quote':quote}]}],
                     'follow_up_questions':['那升级到 4.18.1 应检查什么？']}
        response={'id':'contract-test-response','model':'contract-test-stub','choices':[{'message':{'content':json.dumps(content,ensure_ascii=False)},'finish_reason':'stop'}],
                  'usage':{'prompt_tokens':100,'completion_tokens':80,'total_tokens':180}}
        encoded=json.dumps(response,ensure_ascii=False).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)

    def log_message(self,*args):pass


if __name__=='__main__':
    print('Local protocol test double on 127.0.0.1:8770; this is NOT an LLM.',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8770),Handler).serve_forever()
