"""Собирает самодостаточный HTML-редактор анимаций из tools/webanim/payload.json.

    python tools/make_anim_editor.py
"""
import json, os

ROOT = r"C:\Users\User\Documents\Knyaz2Modding"
PAYLOAD = os.path.join(ROOT, "tools", "webanim", "payload.json")
DEST = os.path.join(ROOT, "anim_editor.html")

HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Князь 2 — редактор анимаций</title>
<style>
:root{--bg:#15171a;--pan:#1e2126;--line:#31363d;--txt:#dfe3e8;--dim:#8b939e;--acc:#e0a458;--sel:#6fd1ff;--key:#7fd18a}
*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--txt);
  font:13px/1.4 "Segoe UI",system-ui,sans-serif}
#app{display:flex;flex-direction:column;height:100%}
header{display:flex;gap:8px;align-items:center;padding:7px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
h1{font-size:14px;margin:0 10px 0 0;font-weight:600;white-space:nowrap}
button,select,input[type=text],input[type=number]{background:#2a2f36;color:var(--txt);
  border:1px solid var(--line);border-radius:5px;padding:4px 9px;font:inherit}
button{cursor:pointer}button:hover{background:#343a43}
button.on{background:var(--acc);color:#16181b;border-color:var(--acc)}
button.pri{background:#2f6d46;border-color:#3c8a59}
input[type=text]{width:150px}input[type=number]{width:58px}
label.chk{display:inline-flex;gap:5px;align-items:center;cursor:pointer;user-select:none;color:var(--dim)}
main{flex:1;display:flex;min-height:0}
#view{flex:1;position:relative;min-width:0;background:#0d0f11}
canvas#bg{position:absolute;inset:0;pointer-events:none;image-rendering:pixelated}
canvas#gl{display:block;width:100%;height:100%;cursor:default;position:relative}
canvas#ov{position:absolute;inset:0;pointer-events:none}
#hint{position:absolute;left:10px;bottom:8px;color:var(--dim);font-size:11px;
  background:rgba(21,23,26,.75);padding:4px 8px;border-radius:4px;pointer-events:none}
aside{width:270px;border-left:1px solid var(--line);background:var(--pan);padding:10px;overflow:auto}
aside h3{margin:12px 0 6px;font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
aside h3:first-child{margin-top:0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:5px}
.row{display:flex;gap:6px;align-items:center;margin:5px 0}
.row span{color:var(--dim);flex:1}
.blist{max-height:190px;overflow:auto;border:1px solid var(--line);border-radius:5px}
.bi{padding:2px 7px;cursor:pointer;border-radius:3px}
.bi:hover{background:#262b32}.bi.sel{background:#2f3a44;outline:1px solid var(--sel)}
.bi.ctl{color:var(--dim)}
footer{border-top:1px solid var(--line);background:var(--pan);padding:7px 10px}
#tl{display:flex;gap:1px;overflow-x:auto;padding-bottom:4px}
.fr{min-width:19px;height:34px;background:#22262c;border-radius:3px;cursor:pointer;
  display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
  font-size:9px;color:#5d656f;padding-bottom:2px;position:relative;flex:1}
.fr:hover{background:#2c323a}
.fr.cur{outline:2px solid var(--sel);color:var(--txt)}
.fr.key{background:#2c4a38}
.fr .d{position:absolute;top:5px;width:7px;height:7px;background:var(--key);
  transform:rotate(45deg);border-radius:1px}
input[type=range]{width:100%}
</style></head><body><div id="app">
<header>
  <h1>Редактор анимаций</h1>
  <select id="clipSel"></select>
  <input type="text" id="clipName" title="имя клипа">
  <span style="color:var(--dim)">кадров</span><input type="number" id="clipLen" min="2" max="240">
  <span style="color:var(--dim)">fps</span><input type="number" id="fps" min="1" max="60">
  <button id="bPlay">▶ играть</button>
  <span style="flex:1"></span>
  <label class="chk"><input type="checkbox" id="cOnion"> калька</label>
  <label class="chk"><input type="checkbox" id="cBones" checked> кости</label>
  <label class="chk"><input type="checkbox" id="cMesh" checked> модель</label>
  <button id="bImport">загрузить .json</button>
  <button class="pri" id="bExport">скачать анимацию</button>
</header>
<main>
  <div id="view"><canvas id="bg"></canvas><canvas id="gl"></canvas><canvas id="ov"></canvas>
    <div id="hint">ЛКМ по точке — тянуть · за цветную ось — строго вдоль неё · X/Y/Z — закрепить ось, Esc — снять · «тянуть родителей» 1 + «дети сохраняют поворот» = двигается одна кость · ПКМ — вид · колесо — зум · Q/E — скрутка</div></div>
  <aside>
    <h3>Эталон из игры</h3>
    <div class="row"><span>подложка</span>
      <select id="refBlock"><option value="">нет</option><option value="stand">стойка (6)</option>
        <option value="walk">ходьба (14)</option><option value="idle">простой (23)</option>
        <option value="run">бег (9)</option></select></div>
    <div class="row"><span>направление</span><select id="refDir"></select></div>
    <div class="row"><span>прозрачность</span><span id="refOpV" style="flex:0">55%</span></div>
    <input type="range" id="refOp" min="0" max="100" value="55">
    <div class="row"><span>увеличение</span><span id="refZoomV" style="flex:0">×3</span></div>
    <input type="range" id="refZoom" min="10" max="80" step="1" value="30">
    <div class="row"><span>сдвиг болвана ↕</span><span id="refDyV" style="flex:0">0 px</span></div>
    <input type="range" id="refDy" min="-40" max="40" step="1" value="0">
    <div class="grid" style="margin-top:6px">
      <button id="bGrid">все направления</button>
      <button id="bIso" class="on">камера игры</button>
      <button id="bDiff">разница</button>
      <button id="bRefFront">эталон поверх</button>
      <button id="bFit">длину клипа = эталону</button>
      <button id="bDy0">сдвиг в ноль</button>
    </div>
    <div class="row"><span>совпадение силуэтов</span><b id="iouv">—</b></div>
    <h3>Захват</h3>
    <div class="row"><span>инструмент</span>
      <button id="tMove" class="on">⇄ двигать</button><button id="tRot">⟳ вращать</button></div>
    <div class="row"><span>режим</span>
      <button id="mIK" class="on">IK</button><button id="mFK">FK</button></div>
    <div class="row"><span>тянуть родителей</span><input type="number" id="chain" min="1" max="5" value="3"></div>
    <label class="chk" style="margin:2px 0 6px"><input type="checkbox" id="cHold"> дети сохраняют поворот</label>
    <button id="bOnly" style="width:100%">двигать только эту кость</button>
    <div class="row"><span>скрутка кости</span><input type="number" id="twist" step="5" value="0"></div>
    <input type="range" id="twistR" min="-180" max="180" step="1" value="0">
    <div class="row"><span>ось движения</span><b id="axv">свободно</b></div>
    <div class="grid" style="grid-template-columns:repeat(4,1fr)">
      <button data-ax="X">X</button><button data-ax="Y">Y</button>
      <button data-ax="Z">Z</button><button data-ax="">свободно</button>
    </div>
    <h3>Выбранная кость</h3>
    <div id="selName" style="font-weight:600;margin-bottom:6px">—</div>
    <div class="blist" id="blist"></div>
    <h3>Поза</h3>
    <div class="grid">
      <button id="bKey">поставить ключ</button>
      <button id="bDelKey">убрать ключ</button>
      <button id="bCopy">копировать</button>
      <button id="bPaste">вставить</button>
      <button id="bMirror">зеркалить</button>
      <button id="bReset">сбросить кость</button>
      <button id="bRestAll">вся поза в покой</button>
      <button id="bLoop">замкнуть цикл</button>
    </div>
    <h3>Вид</h3>
    <div class="grid">
      <button data-cam="front">фас</button><button data-cam="side">профиль</button>
      <button data-cam="q34">3/4</button><button data-cam="top">сверху</button>
    </div>
    <h3>Сведения</h3>
    <div id="info" style="color:var(--dim);font-size:11px"></div>
  </aside>
</main>
<footer><div id="tl"></div></footer>
</div>
<script>
const P = __PAYLOAD__;
const REF = __REFPAYLOAD__;
// ---------------------------------------------------------------- математика
const qmul=(a,b)=>[a[0]*b[0]-a[1]*b[1]-a[2]*b[2]-a[3]*b[3],
 a[0]*b[1]+a[1]*b[0]+a[2]*b[3]-a[3]*b[2],
 a[0]*b[2]-a[1]*b[3]+a[2]*b[0]+a[3]*b[1],
 a[0]*b[3]+a[1]*b[2]-a[2]*b[1]+a[3]*b[0]];
const qcon=q=>[q[0],-q[1],-q[2],-q[3]];
const qnorm=q=>{const l=Math.hypot(q[0],q[1],q[2],q[3])||1;return[q[0]/l,q[1]/l,q[2]/l,q[3]/l];};
const qrot=(q,v)=>{const t=[2*(q[2]*v[2]-q[3]*v[1]),2*(q[3]*v[0]-q[1]*v[2]),2*(q[1]*v[1]-q[2]*v[0])];
 return[v[0]+q[0]*t[0]+q[2]*t[2]-q[3]*t[1],v[1]+q[0]*t[1]+q[3]*t[0]-q[1]*t[2],
        v[2]+q[0]*t[2]+q[1]*t[1]-q[2]*t[0]];};
const qaxis=(ax,an)=>{const s=Math.sin(an/2);return[Math.cos(an/2),ax[0]*s,ax[1]*s,ax[2]*s];};
function qfromto(a,b){const d=a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
 if(d>0.999999)return[1,0,0,0];
 if(d<-0.999999){let o=Math.abs(a[0])<0.9?[1,0,0]:[0,1,0];
   let c=[a[1]*o[2]-a[2]*o[1],a[2]*o[0]-a[0]*o[2],a[0]*o[1]-a[1]*o[0]];
   const l=Math.hypot(...c)||1;return[0,c[0]/l,c[1]/l,c[2]/l];}
 const c=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
 return qnorm([1+d,c[0],c[1],c[2]]);}
function qslerp(a,b,t){let d=a[0]*b[0]+a[1]*b[1]+a[2]*b[2]+a[3]*b[3];let bb=b.slice();
 if(d<0){d=-d;bb=bb.map(v=>-v);}
 if(d>0.9995)return qnorm(a.map((v,i)=>v+(bb[i]-v)*t));
 const th=Math.acos(d),s=Math.sin(th);
 const w1=Math.sin((1-t)*th)/s,w2=Math.sin(t*th)/s;
 return qnorm(a.map((v,i)=>v*w1+bb[i]*w2));}
function qFromMat3(m){ // m: [c0x,c0y,c0z, c1x,..] по столбцам
 const t=m[0]+m[4]+m[8];let q;
 if(t>0){const s=Math.sqrt(t+1)*2;q=[s/4,(m[5]-m[7])/s,(m[6]-m[2])/s,(m[1]-m[3])/s];}
 else if(m[0]>m[4]&&m[0]>m[8]){const s=Math.sqrt(1+m[0]-m[4]-m[8])*2;
   q=[(m[5]-m[7])/s,s/4,(m[3]+m[1])/s,(m[6]+m[2])/s];}
 else if(m[4]>m[8]){const s=Math.sqrt(1+m[4]-m[0]-m[8])*2;
   q=[(m[6]-m[2])/s,(m[3]+m[1])/s,s/4,(m[7]+m[5])/s];}
 else{const s=Math.sqrt(1+m[8]-m[0]-m[4])*2;
   q=[(m[1]-m[3])/s,(m[6]+m[2])/s,(m[7]+m[5])/s,s/4];}
 return qnorm(q);}
function m4(q,p){const[w,x,y,z]=q;
 return new Float32Array([1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w),0,
  2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w),0,
  2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y),0, p[0],p[1],p[2],1]);}
function m4mul(a,b){const o=new Float32Array(16);
 for(let c=0;c<4;c++)for(let r=0;r<4;r++){let s=0;
  for(let k=0;k<4;k++)s+=a[k*4+r]*b[c*4+k];o[c*4+r]=s;}return o;}
function m4invRigid(m){const o=new Float32Array(16);
 for(let r=0;r<3;r++)for(let c=0;c<3;c++)o[c*4+r]=m[r*4+c];
 for(let r=0;r<3;r++)o[12+r]=-(o[r]*m[12]+o[4+r]*m[13]+o[8+r]*m[14]);
 o[15]=1;return o;}
function persp(f,a,n,fa){const t=1/Math.tan(f/2);
 return new Float32Array([t/a,0,0,0, 0,t,0,0, 0,0,(fa+n)/(n-fa),-1, 0,0,2*fa*n/(n-fa),0]);}
function lookAt(e,c,u){let z=[e[0]-c[0],e[1]-c[1],e[2]-c[2]];let l=Math.hypot(...z);z=z.map(v=>v/l);
 let x=[u[1]*z[2]-u[2]*z[1],u[2]*z[0]-u[0]*z[2],u[0]*z[1]-u[1]*z[0]];l=Math.hypot(...x)||1;x=x.map(v=>v/l);
 const y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]];
 return new Float32Array([x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0,
  -(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]),-(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]),-(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]),1]);}

// ---------------------------------------------------------------- скелет
const B=P.bones, NB=B.length;
const NAMES=B.map(b=>b.name), IDX={}; NAMES.forEach((n,i)=>IDX[n]=i);
const restQ=[],restP=[],relQ=[],relP=[],invRest=[];
for(let i=0;i<NB;i++){const m=B[i].rest;
 restQ[i]=qFromMat3([m[0],m[1],m[2],m[4],m[5],m[6],m[8],m[9],m[10]]);
 restP[i]=[m[12],m[13],m[14]];
 invRest[i]=m4invRigid(new Float32Array(m));}
for(let i=0;i<NB;i++){const p=B[i].parent;
 if(p<0){relQ[i]=restQ[i];relP[i]=restP[i];}
 else{const ic=qcon(restQ[p]);relQ[i]=qmul(ic,restQ[i]);
   relP[i]=qrot(ic,[restP[i][0]-restP[p][0],restP[i][1]-restP[p][1],restP[i][2]-restP[p][2]]);}}
const ORDER=[];{const seen=new Set();
 const em=i=>{if(seen.has(i))return;if(B[i].parent>=0)em(B[i].parent);seen.add(i);ORDER.push(i);};
 for(let i=0;i<NB;i++)em(i);}
const CHILDREN=B.map(()=>[]); B.forEach((b,i)=>{if(b.parent>=0)CHILDREN[b.parent].push(i);});

function newPose(){return{q:Array.from({length:NB},()=>[1,0,0,0]),loc:[0,0,0]};}
function clonePose(p){return{q:p.q.map(v=>v.slice()),loc:p.loc.slice()};}
let pose=newPose();
const wQ=[],wP=[];
function evalPose(ps){
 for(const i of ORDER){const p=B[i].parent, lq=ps.q[i];
  const isRoot=(i===IDX["root"]);
  const loc=isRoot?ps.loc:[0,0,0];
  if(p<0){const bq=relQ[i];wQ[i]=qmul(bq,lq);
    const t=qrot(bq,loc);wP[i]=[relP[i][0]+t[0],relP[i][1]+t[1],relP[i][2]+t[2]];}
  else{const bq=qmul(wQ[p],relQ[i]);wQ[i]=qmul(bq,lq);
    const a=qrot(wQ[p],relP[i]),t=qrot(bq,loc);
    wP[i]=[wP[p][0]+a[0]+t[0],wP[p][1]+a[1]+t[1],wP[p][2]+a[2]+t[2]];}}}
const head=i=>wP[i];
const tail=i=>{const d=qrot(wQ[i],[0,B[i].length,0]);return[wP[i][0]+d[0],wP[i][1]+d[1],wP[i][2]+d[2]];};
function skinMats(){const o=new Float32Array(NB*16);
 for(let i=0;i<NB;i++)o.set(m4mul(m4(wQ[i],wP[i]),invRest[i]),i*16);return o;}
// повернуть кость так, чтобы её МИРОВОЙ поворот стал qw*старый
function applyWorld(ps,i,qw){const p=B[i].parent;
 const bq=p<0?relQ[i]:qmul(wQ[p],relQ[i]);
 ps.q[i]=qnorm(qmul(qmul(qcon(bq),qmul(qw,bq)),ps.q[i]));}

// ---------------------------------------------------------------- буферы
function bytes(b64){const s=atob(b64),a=new Uint8Array(s.length);
 for(let i=0;i<s.length;i++)a[i]=s.charCodeAt(i);return a;}
const BUF={pos:new Float32Array(bytes(P.buffers.pos).buffer),
 nor:new Float32Array(bytes(P.buffers.nor).buffer),
 si:bytes(P.buffers.skin_idx), sw:bytes(P.buffers.skin_wt),
 idx:new Uint16Array(bytes(P.buffers.idx).buffer)};

// ---------------------------------------------------------------- WebGL
const cv=document.getElementById("gl"),ov=document.getElementById("ov"),oc=ov.getContext("2d");
const bg=document.getElementById("bg"),bc=bg.getContext("2d");
// alpha:true — модель рисуется поверх слоя с эталонным спрайтом
const gl=cv.getContext("webgl",{antialias:true,alpha:true,premultipliedAlpha:false});
const VS=`attribute vec3 aP;attribute vec3 aN;attribute vec4 aI;attribute vec4 aW;
uniform mat4 uMVP,uM;uniform mat4 uB[`+NB+`];varying vec3 vN;varying vec3 vP;
void main(){mat4 s=uB[int(aI.x)]*aW.x+uB[int(aI.y)]*aW.y+uB[int(aI.z)]*aW.z+uB[int(aI.w)]*aW.w;
 vec4 p=s*vec4(aP,1.0);vN=mat3(s)*aN;vP=p.xyz;gl_Position=uMVP*p;}`;
const FS=`precision mediump float;varying vec3 vN;varying vec3 vP;uniform vec3 uCam;
void main(){vec3 n=normalize(vN);vec3 v=normalize(uCam-vP);
 vec3 l=normalize(v+vec3(0.22,0.0,0.85));            // фонарь у камеры, чуть сверху
 float d=max(dot(n,l),0.0)*0.70+0.32;
 float rim=pow(1.0-max(dot(n,v),0.0),2.5)*0.16;
 float s=pow(max(dot(reflect(-l,n),v),0.0),28.0)*0.20;
 gl_FragColor=vec4(vec3(0.82,0.83,0.86)*d+s+rim,1.0);}`;
function sh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);
 if(!gl.getShaderParameter(o,gl.COMPILE_STATUS))throw gl.getShaderInfoLog(o);return o;}
const prog=gl.createProgram();
gl.attachShader(prog,sh(gl.VERTEX_SHADER,VS));gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,FS));
gl.linkProgram(prog);
if(!gl.getProgramParameter(prog,gl.LINK_STATUS))throw gl.getProgramInfoLog(prog);
gl.useProgram(prog);
function ab(data,n,type,norm,attr){const b=gl.createBuffer();
 gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);
 const l=gl.getAttribLocation(prog,attr);gl.enableVertexAttribArray(l);
 gl.vertexAttribPointer(l,n,type,norm,0,0);}
ab(BUF.pos,3,gl.FLOAT,false,"aP"); ab(BUF.nor,3,gl.FLOAT,false,"aN");
ab(BUF.si,4,gl.UNSIGNED_BYTE,false,"aI"); ab(BUF.sw,4,gl.UNSIGNED_BYTE,true,"aW");
const eb=gl.createBuffer();
gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,eb);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,BUF.idx,gl.STATIC_DRAW);
const uMVP=gl.getUniformLocation(prog,"uMVP"),uB=gl.getUniformLocation(prog,"uB"),
      uCam=gl.getUniformLocation(prog,"uCam");
gl.enable(gl.DEPTH_TEST);

// ---------------------------------------------------------------- камера
const C={az:0,el:0.12,dist:3.2,tx:0,ty:0,tz:0.0};
const lo=P.bounds.lo,hi=P.bounds.hi;C.tz=(lo[2]+hi[2])/2;
const Z_FEET=lo[2];
const ANCHOR_FRAC=0.80;                 // где на холсте стоит ТОЧКА НОГ
const RS={block:"",dir:"SE",op:0.55,zoom:3,iso:true,diff:false,front:false,grid:false,dy:0};
const GRID={cols:4,rows:2,dirs:["W","NW","N","NE","E","SE","S","SW"]};
const refImg={};
function refStrip(dir){
 if(!RS.block)return null;
 const k=RS.block+"/"+dir;
 if(!refImg[k]){const im=new Image();im.onload=draw;
  im.src=REF.blocks[RS.block].strips[dir];refImg[k]=im;}
 return refImg[k].complete?refImg[k]:null;}
const isoOn=()=>RS.iso&&RS.block;
const gridOn=()=>RS.grid&&RS.block;
function camPos(dir){
 if(isoOn()){const t=REF.tilt*Math.PI/180,a=(REF.az[dir||RS.dir]||0)*Math.PI/180,D=20;
  return[D*Math.cos(t)*Math.sin(a),-D*Math.cos(t)*Math.cos(a),Z_FEET+D*Math.sin(t)];}
 const ce=Math.cos(C.el);
 return[C.tx+C.dist*ce*Math.sin(C.az),C.ty-C.dist*ce*Math.cos(C.az),C.tz+C.dist*Math.sin(C.el)];}
const camTgt=()=>isoOn()?[0,0,Z_FEET]:[C.tx,C.ty,C.tz];
function ortho(w,h,n,f,ox,oy){
 return new Float32Array([2/w,0,0,0, 0,2/h,0,0, 0,0,-2/(f-n),0, ox,oy,-(f+n)/(f-n),1]);}
function refFrame(){const n=REF.blocks[RS.block].frames;return Math.min(n-1,(frame-1)%n);}
// ---- список видов: один на весь холст либо сетка 4x2 ----
function views(){
 if(!gridOn())return[{dir:RS.dir,rect:{x:0,y:0,w:cv.width,h:cv.height}}];
 const cw=cv.width/GRID.cols,ch=cv.height/GRID.rows;
 return GRID.dirs.map((d,i)=>({dir:d,
  rect:{x:(i%GRID.cols)*cw,y:Math.floor(i/GRID.cols)*ch,w:cw,h:ch}}));}
function vpFor(v){
 const d=window.devicePixelRatio||1;
 if(!isoOn())return m4mul(persp(0.72,v.rect.w/v.rect.h,0.05,40),
                          lookAt(camPos(),camTgt(),[0,0,1]));
 const pxu=REF.px_per_unit*RS.zoom*d;
 const oy=(1-2*ANCHOR_FRAC)-2*RS.dy*d/v.rect.h;      // сдвиг болвана по высоте
 return m4mul(ortho(v.rect.w/pxu,v.rect.h/pxu,0.1,80,0,oy),
              lookAt(camPos(v.dir),[0,0,Z_FEET],[0,0,1]));}
const anchorOf=r=>[r.x+r.w/2,r.y+r.h*ANCHOR_FRAC];
function blitRef(g,alpha,v){
 const im=refStrip(v.dir);if(!im)return false;
 const w=REF.window,d=window.devicePixelRatio||1,z=RS.zoom*d,[ax,ay]=anchorOf(v.rect);
 g.imageSmoothingEnabled=false;g.globalAlpha=alpha;
 g.drawImage(im,refFrame()*w.w,0,w.w,w.h, ax-w.ax*z, ay-w.ay*z, w.w*z, w.h*z);
 g.globalAlpha=1;return true;}
let VP=null;
function resize(){const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;
 for(const c of [cv,ov,bg]){c.width=Math.max(1,r.width*d);c.height=Math.max(1,r.height*d);
  c.style.width=r.width+"px";c.style.height=r.height+"px";}}
let VIEWS=[],ACT=null;                    // ACT — вид, в котором идёт правка
function projIn(p,M,r){const v=[p[0],p[1],p[2],1],o=[0,0,0,0];
 for(let q=0;q<4;q++){let s=0;for(let k=0;k<4;k++)s+=M[k*4+q]*v[k];o[q]=s;}
 if(o[3]<=0)return null;
 return[r.x+(o[0]/o[3]*0.5+0.5)*r.w, r.y+(0.5-o[1]/o[3]*0.5)*r.h, o[3]];}
function project(p){return ACT?projIn(p,ACT.vp,ACT.rect):null;}
function viewAt(mx,my){
 for(const v of VIEWS){const r=v.rect;
  if(mx>=r.x&&mx<r.x+r.w&&my>=r.y&&my<r.y+r.h)return v;}
 return ACT;}

function drawDiff(){
 const W=ov.width,H=ov.height;
 const t=document.createElement("canvas");t.width=W;t.height=H;
 const tg=t.getContext("2d");
 let any=false;
 for(const v of VIEWS)any=blitRef(tg,1,v)||any;
 if(!any)return;
 const A=tg.getImageData(0,0,W,H).data;
 tg.clearRect(0,0,W,H);tg.drawImage(cv,0,0);
 const B=tg.getImageData(0,0,W,H).data;
 const out=oc.createImageData(W,H),O=out.data;
 let both=0,onlyA=0,onlyB=0;
 for(let i=0;i<A.length;i+=4){
  const a=A[i+3]>8,b=B[i+3]>8;
  if(!a&&!b){O[i+3]=0;continue;}
  if(a&&b)both++;else if(a)onlyA++;else onlyB++;
  O[i]=b?235:26;O[i+1]=(a&&b)?235:26;O[i+2]=a?235:26;O[i+3]=255;}
 oc.putImageData(out,0,0);
 const u=both+onlyA+onlyB;
 document.getElementById("iouv").textContent=u?(both/u).toFixed(3):"—";}

function draw(){
 resize();
 evalPose(pose);
 VIEWS=views().map(v=>Object.assign({},v,{vp:vpFor(v)}));
 ACT=VIEWS.find(v=>v.dir===RS.dir)||VIEWS[0];
 VP=ACT.vp;
 bc.setTransform(1,0,0,1,0,0);bc.clearRect(0,0,bg.width,bg.height);
 bc.fillStyle="#0d0f11";bc.fillRect(0,0,bg.width,bg.height);
 if(RS.block&&!RS.front&&!RS.diff)for(const v of VIEWS)blitRef(bc,RS.op,v);
 cv.style.opacity=RS.diff?0:1; bg.style.opacity=RS.diff?0:1;
 gl.viewport(0,0,cv.width,cv.height);
 gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
 if(document.getElementById("cMesh").checked){
  gl.uniformMatrix4fv(uB,false,skinMats());
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,eb);
  for(const v of VIEWS){
   gl.viewport(v.rect.x,cv.height-v.rect.y-v.rect.h,v.rect.w,v.rect.h);
   gl.uniformMatrix4fv(uMVP,false,v.vp);
   gl.uniform3fv(uCam,new Float32Array(camPos(v.dir)));
   gl.drawElements(gl.TRIANGLES,BUF.idx.length,gl.UNSIGNED_SHORT,0);}
  gl.viewport(0,0,cv.width,cv.height);}
 oc.setTransform(1,0,0,1,0,0);
 oc.clearRect(0,0,ov.width,ov.height);
 if(RS.diff&&RS.block)drawDiff();
 else if(RS.block&&RS.front)for(const v of VIEWS)blitRef(oc,RS.op,v);
 if(document.getElementById("cOnion").checked)onion();
 if(document.getElementById("cBones").checked)overlay();
 if(gridOn()){const d=window.devicePixelRatio||1;
  oc.font=(12*d)+"px Segoe UI";
  for(const v of VIEWS){
   oc.fillStyle=v===ACT?"#6fd1ff":"rgba(180,190,205,.65)";
   oc.fillText(v.dir+(v===ACT?"  ← правим здесь":""),v.rect.x+7*d,v.rect.y+15*d);
   oc.strokeStyle=v===ACT?"rgba(111,209,255,.55)":"rgba(120,130,145,.22)";
   oc.lineWidth=(v===ACT?2:1)*d;
   oc.strokeRect(v.rect.x+1,v.rect.y+1,v.rect.w-2,v.rect.h-2);}}
}
function drawSkel(ps,col,v){
 evalPose(ps);const pts=[];
 for(let i=0;i<NB;i++)pts[i]={h:projIn(head(i),v.vp,v.rect),t:projIn(tail(i),v.vp,v.rect)};
 oc.lineWidth=2*(window.devicePixelRatio||1);
 for(let i=0;i<NB;i++){const a=pts[i].h,b=pts[i].t;if(!a||!b)continue;
  oc.strokeStyle=B[i].deform?col:"rgba(140,150,165,.35)";   // root — управляющая, бледнее
  oc.beginPath();oc.moveTo(a[0],a[1]);oc.lineTo(b[0],b[1]);oc.stroke();}
 return pts;}
let HANDLES=[];
function overlay(){
 const d=window.devicePixelRatio||1;
 HANDLES=[];
 for(const v of VIEWS){
  const act=v===ACT;
  const pts=drawSkel(pose,act?"rgba(224,164,88,.85)":"rgba(224,164,88,.40)",v);
  if(!act)continue;                       // точки только в активном виде
  for(let i=0;i<NB;i++){const t=pts[i].t;if(!t)continue;
   HANDLES.push({i,x:t[0],y:t[1]});
   const on=i===selBone;
   oc.beginPath();oc.arc(t[0],t[1],(on?7:4.5)*d,0,7);
   oc.fillStyle=on?"#6fd1ff":(NAMES[i].endsWith(".R")?"#b9752f":"#e0a458");
   oc.fill();oc.lineWidth=1.5*d;oc.strokeStyle="#10131a";oc.stroke();}
  if(selBone>=0&&pts[selBone].t){const t=pts[selBone].t;
   oc.fillStyle="#6fd1ff";oc.font=(12*d)+"px Segoe UI";
   oc.fillText(NAMES[selBone],t[0]+11*d,t[1]-9*d);}}
 drawGizmo();
 evalPose(pose);
}
function onion(){
 const ks=keyFrames();
 const prev=ks.filter(f=>f<frame).pop(), next=ks.filter(f=>f>frame)[0];
 for(const[f,c] of [[prev,"rgba(110,170,255,.30)"],[next,"rgba(255,120,120,.30)"]])
  if(f!==undefined)for(const v of VIEWS)drawSkel(poseAt(f),c,v);
 evalPose(pose);
}

// ---------------------------------------------------------------- клипы
let clips={},clip=null,frame=1,selBone=IDX["hand.L"],playing=false,clipboard=null;
for(const n in P.clips){const c=P.clips[n];
 const keys={};
 for(const f in c.keys){const k=c.keys[f];
  keys[f]={q:NAMES.map(nm=>(k.bones[nm]||[1,0,0,0]).slice()),loc:k.root.slice()};}
 clips[n]={name:n,fps:24,length:c.length,keys};}
clips["Новый"]={name:"Новый",fps:24,length:24,keys:{1:clonePose(newPose())}};
function keyFrames(){return Object.keys(clip.keys).map(Number).sort((a,b)=>a-b);}
function poseAt(f){
 const ks=keyFrames();if(!ks.length)return newPose();
 if(clip.keys[f])return clonePose(clip.keys[f]);
 const a=ks.filter(k=>k<=f).pop(), b=ks.filter(k=>k>=f)[0];
 if(a===undefined)return clonePose(clip.keys[b]);
 if(b===undefined)return clonePose(clip.keys[a]);
 const t=(f-a)/(b-a),A=clip.keys[a],Bk=clip.keys[b];
 return{q:A.q.map((q,i)=>qslerp(q,Bk.q[i],t)),
        loc:A.loc.map((v,i)=>v+(Bk.loc[i]-v)*t)};}
function setFrame(f){frame=Math.max(1,Math.min(clip.length,f));pose=poseAt(frame);ui();draw();}
function ensureKey(){if(!clip.keys[frame])clip.keys[frame]=clonePose(pose);return clip.keys[frame];}
function commit(){const k=ensureKey();k.q=pose.q.map(v=>v.slice());k.loc=pose.loc.slice();}

// ---------------------------------------------------------------- IK
// Изоляция потомков: правка кости не должна разворачивать то, что висит ниже.
// Достаточно вернуть мировой поворот ПРЯМЫМ детям — внуки поедут за ними сами,
// их локальные повороты мы не трогали. Позиции детей всё равно сместятся: они
// прибиты к концу кости, это уже не поворот, а сама связь скелета.
function withHold(i,fn){
 if(!document.getElementById("cHold").checked){fn();return;}
 evalPose(pose);
 const kids=CHILDREN[i],saved=kids.map(c=>wQ[c].slice());
 fn();
 evalPose(pose);
 kids.forEach((c,k)=>{
  const p=B[c].parent;
  const bq=p<0?relQ[c]:qmul(wQ[p],relQ[c]);
  pose.q[c]=qnorm(qmul(qcon(bq),saved[k]));});
 evalPose(pose);}
function chainOf(endI,depth){
 const c=[];let i=endI;
 for(let k=0;k<depth&&i>=0;k++){c.push(i);i=B[i].parent;}
 return c;}
// начало цепи и её предельная длина — цель дальше него недостижима
function chainReach(chain){
 evalPose(pose);
 let r=0;for(const b of chain)r+=B[b].length;
 return{S:head(chain[chain.length-1]).slice(),reach:r*0.999};}
function ccd(endI,target,depth,iters){
 const chain=chainOf(endI,depth);
 // Обрезаем цель по досягаемости: у предела вытягивания CCD залипает и уводит вбок.
 const{S,reach}=chainReach(chain);
 const t=[target[0]-S[0],target[1]-S[1],target[2]-S[2]],L=Math.hypot(...t);
 if(L>reach)target=[S[0]+t[0]*reach/L,S[1]+t[1]*reach/L,S[2]+t[2]*reach/L];
 for(let it=0;it<(iters||10);it++)
  for(const bi of chain){
   evalPose(pose);
   const e=tail(endI),p=head(bi);
   let a=[e[0]-p[0],e[1]-p[1],e[2]-p[2]],b=[target[0]-p[0],target[1]-p[1],target[2]-p[2]];
   const la=Math.hypot(...a),lb=Math.hypot(...b);
   if(la<1e-5||lb<1e-5)continue;
   a=a.map(v=>v/la);b=b.map(v=>v/lb);
   applyWorld(pose,bi,qfromto(a,b));}
 evalPose(pose);}

// ---------------------------------------------------------------- ввод
let drag=null,orbit=null;
cv.addEventListener("contextmenu",e=>e.preventDefault());
cv.addEventListener("mousedown",e=>{
 const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;
 const mx=(e.clientX-r.left)*d,my=(e.clientY-r.top)*d;
 if(e.button===2||e.button===1){orbit={x:e.clientX,y:e.clientY,az:C.az,el:C.el,
   tx:C.tx,ty:C.ty,tz:C.tz,pan:e.shiftKey};return;}
 const v=viewAt(mx,my);                    // клик по ячейке делает её рабочей
 if(v&&v!==ACT){RS.dir=v.dir;refDir.value=v.dir;draw();}
 const depth=+document.getElementById("chain").value;
 if(tool==="rot"&&selBone>=0){             // кольца вращения имеют приоритет
  evalPose(pose);
  const piv=head(selBone).slice();
  const rr=hitRot(mx,my,piv);
  if(rr){const a0=ringAngle(ACT,mx,my,piv,rr);
   if(a0!==null){drag={rot:{axis:rr.a,ring:rr,piv,a0,deg:0},i:selBone,depth,
                       start:clonePose(pose)};draw();return;}}}
 const ax=tool==="rot"?null:hitAxis(mx,my); // сначала гизмо: у него приоритет над точками
 if(ax){evalPose(pose);
  const J=tail(selBone).slice(),s0=axisParam(ACT,mx,my,J,ax.v);
  if(s0!==null){drag={i:selBone,depth,axis:ax,J0:J,s0};draw();return;}}
 let best=null,bd=18*d;
 for(const h of HANDLES){const dd=Math.hypot(h.x-mx,h.y-my);if(dd<bd){bd=dd;best=h;}}
 if(best){selBone=best.i;
  const A=axisLock?AXES.find(a=>a.n===axisLock):null;
  evalPose(pose);
  const J=tail(best.i).slice();
  drag={i:best.i,depth,axis:A,J0:J,s0:A?axisParam(ACT,mx,my,J,A.v):0};
  ui();draw();}});
window.addEventListener("mousemove",e=>{
 if(orbit){const dx=e.clientX-orbit.x,dy=e.clientY-orbit.y;
  if(isoOn()){orbit=null;return;}          // камера игры зафиксирована
  if(orbit.pan){const s=C.dist*0.0022;
   C.tx=orbit.tx-Math.cos(C.az)*dx*s;C.ty=orbit.ty-Math.sin(C.az)*dx*s;C.tz=orbit.tz+dy*s;}
  else{C.az=orbit.az+dx*0.008;C.el=Math.max(-1.4,Math.min(1.4,orbit.el-dy*0.008));}
  draw();return;}
 if(!drag)return;
 const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;
 const mx=(e.clientX-r.left)*d,my=(e.clientY-r.top)*d;
 evalPose(pose);
 if(drag.rot){                        // вращение вокруг мировой оси через начало кости
  const R=drag.rot;
  const a=ringAngle(ACT,mx,my,R.piv,R.ring);
  if(a===null)return;
  let dA=a-R.a0;
  while(dA>Math.PI)dA-=2*Math.PI;
  while(dA<-Math.PI)dA+=2*Math.PI;
  if(e.shiftKey)dA=Math.round(dA/(Math.PI/36))*(Math.PI/36);   // шаг 5° с Shift
  R.deg=dA*180/Math.PI;
  pose=clonePose(drag.start);evalPose(pose);
  withHold(drag.i,()=>{applyWorld(pose,drag.i,qaxis(R.axis.v,dA));});
  commit();ui();draw();return;}
 let p;
 if(drag.axis){                             // движение строго вдоль одной мировой оси
  const s=axisParam(ACT,mx,my,drag.J0,drag.axis.v);
  if(s===null)return;
  let k=s-drag.s0;const A=drag.axis.v;
  // Упор в предел вытягивания решаем ПО ОСИ, а не обрезкой к сфере, — иначе
  // точка соскочит с оси. Ищем пересечение прямой с шаром досягаемости.
  const{S,reach}=chainReach(chainOf(drag.i,drag.depth));
  const w=[drag.J0[0]-S[0],drag.J0[1]-S[1],drag.J0[2]-S[2]];
  const b=A[0]*w[0]+A[1]*w[1]+A[2]*w[2];
  const disc=b*b-(w[0]*w[0]+w[1]*w[1]+w[2]*w[2]-reach*reach);
  if(disc>0){const rt=Math.sqrt(disc);k=Math.max(-b-rt,Math.min(-b+rt,k));}
  p=[drag.J0[0]+A[0]*k,drag.J0[1]+A[1]*k,drag.J0[2]+A[2]*k];
 } else p=rayPoint(ACT,mx,my,tail(drag.i));
 withHold(drag.i,()=>{
  if(document.getElementById("mFK").classList.contains("on")){
   evalPose(pose);const h=head(drag.i),t=tail(drag.i);
   let a=[t[0]-h[0],t[1]-h[1],t[2]-h[2]],b=[p[0]-h[0],p[1]-h[1],p[2]-h[2]];
   const la=Math.hypot(...a),lb=Math.hypot(...b);
   if(la>1e-5&&lb>1e-5)applyWorld(pose,drag.i,qfromto(a.map(v=>v/la),b.map(v=>v/lb)));
  } else ccd(drag.i,p,drag.depth);});
 commit();ui();draw();});
window.addEventListener("mouseup",()=>{drag=null;orbit=null;});
cv.addEventListener("wheel",e=>{e.preventDefault();
 if(isoOn()){RS.zoom=Math.max(1,Math.min(8,RS.zoom*(e.deltaY<0?1.12:1/1.12)));
  refZoom.value=Math.round(RS.zoom*10);refZoomV.textContent="×"+RS.zoom.toFixed(1);draw();return;}
 C.dist=Math.max(0.4,Math.min(14,C.dist*(e.deltaY<0?1/1.12:1.12)));draw();},{passive:false});
function invMat(m){ // численная инверсия 4x4
 const a=[];for(let i=0;i<16;i++)a[i]=m[i];
 const inv=new Float64Array(16);
 inv[0]=a[5]*a[10]*a[15]-a[5]*a[11]*a[14]-a[9]*a[6]*a[15]+a[9]*a[7]*a[14]+a[13]*a[6]*a[11]-a[13]*a[7]*a[10];
 inv[4]=-a[4]*a[10]*a[15]+a[4]*a[11]*a[14]+a[8]*a[6]*a[15]-a[8]*a[7]*a[14]-a[12]*a[6]*a[11]+a[12]*a[7]*a[10];
 inv[8]=a[4]*a[9]*a[15]-a[4]*a[11]*a[13]-a[8]*a[5]*a[15]+a[8]*a[7]*a[13]+a[12]*a[5]*a[11]-a[12]*a[7]*a[9];
 inv[12]=-a[4]*a[9]*a[14]+a[4]*a[10]*a[13]+a[8]*a[5]*a[14]-a[8]*a[6]*a[13]-a[12]*a[5]*a[10]+a[12]*a[6]*a[9];
 inv[1]=-a[1]*a[10]*a[15]+a[1]*a[11]*a[14]+a[9]*a[2]*a[15]-a[9]*a[3]*a[14]-a[13]*a[2]*a[11]+a[13]*a[3]*a[10];
 inv[5]=a[0]*a[10]*a[15]-a[0]*a[11]*a[14]-a[8]*a[2]*a[15]+a[8]*a[3]*a[14]+a[12]*a[2]*a[11]-a[12]*a[3]*a[10];
 inv[9]=-a[0]*a[9]*a[15]+a[0]*a[11]*a[13]+a[8]*a[1]*a[15]-a[8]*a[3]*a[13]-a[12]*a[1]*a[11]+a[12]*a[3]*a[9];
 inv[13]=a[0]*a[9]*a[14]-a[0]*a[10]*a[13]-a[8]*a[1]*a[14]+a[8]*a[2]*a[13]+a[12]*a[1]*a[10]-a[12]*a[2]*a[9];
 inv[2]=a[1]*a[6]*a[15]-a[1]*a[7]*a[14]-a[5]*a[2]*a[15]+a[5]*a[3]*a[14]+a[13]*a[2]*a[7]-a[13]*a[3]*a[6];
 inv[6]=-a[0]*a[6]*a[15]+a[0]*a[7]*a[14]+a[4]*a[2]*a[15]-a[4]*a[3]*a[14]-a[12]*a[2]*a[7]+a[12]*a[3]*a[6];
 inv[10]=a[0]*a[5]*a[15]-a[0]*a[7]*a[13]-a[4]*a[1]*a[15]+a[4]*a[3]*a[13]+a[12]*a[1]*a[7]-a[12]*a[3]*a[5];
 inv[14]=-a[0]*a[5]*a[14]+a[0]*a[6]*a[13]+a[4]*a[1]*a[14]-a[4]*a[2]*a[13]-a[12]*a[1]*a[6]+a[12]*a[2]*a[5];
 inv[3]=-a[1]*a[6]*a[11]+a[1]*a[7]*a[10]+a[5]*a[2]*a[11]-a[5]*a[3]*a[10]-a[9]*a[2]*a[7]+a[9]*a[3]*a[6];
 inv[7]=a[0]*a[6]*a[11]-a[0]*a[7]*a[10]-a[4]*a[2]*a[11]+a[4]*a[3]*a[10]+a[8]*a[2]*a[7]-a[8]*a[3]*a[6];
 inv[11]=-a[0]*a[5]*a[11]+a[0]*a[7]*a[9]+a[4]*a[1]*a[11]-a[4]*a[3]*a[9]-a[8]*a[1]*a[7]+a[8]*a[3]*a[5];
 inv[15]=a[0]*a[5]*a[10]-a[0]*a[6]*a[9]-a[4]*a[1]*a[10]+a[4]*a[2]*a[9]+a[8]*a[1]*a[6]-a[8]*a[2]*a[5];
 let det=a[0]*inv[0]+a[1]*inv[4]+a[2]*inv[8]+a[3]*inv[12];det=det?1/det:0;
 for(let i=0;i<16;i++)inv[i]*=det;return inv;}
// Луч из-под курсора в мировых координатах. Годится и для перспективы, и для ортографии.
function mouseRay(v,mx,my){
 const inv=invMat(v.vp);
 const ndc=[(mx-v.rect.x)/v.rect.w*2-1, 1-(my-v.rect.y)/v.rect.h*2];
 const na=mulv(inv,[ndc[0],ndc[1],-1,1]), fa=mulv(inv,[ndc[0],ndc[1],1,1]);
 const n=[na[0]/na[3],na[1]/na[3],na[2]/na[3]];
 const f=[fa[0]/fa[3],fa[1]/fa[3],fa[2]/fa[3]];
 let u=[f[0]-n[0],f[1]-n[1],f[2]-n[2]];const L=Math.hypot(...u)||1;
 return{n,u:u.map(c=>c/L)};}
// Точка на луче, лежащая в плоскости экрана через сустав J (свободное перетаскивание).
function rayPoint(v,mx,my,J){
 const{n,u}=mouseRay(v,mx,my);
 const t=(J[0]-n[0])*u[0]+(J[1]-n[1])*u[1]+(J[2]-n[2])*u[2];
 return[n[0]+u[0]*t,n[1]+u[1]*t,n[2]+u[2]*t];}
// Параметр вдоль оси A через J: ближайшая к лучу точка прямой (движение по одной оси).
function axisParam(v,mx,my,J,A){
 const{n,u}=mouseRay(v,mx,my);
 const w=[J[0]-n[0],J[1]-n[1],J[2]-n[2]];
 const b=A[0]*u[0]+A[1]*u[1]+A[2]*u[2];
 const d=A[0]*w[0]+A[1]*w[1]+A[2]*w[2];
 const e=u[0]*w[0]+u[1]*w[1]+u[2]*w[2];
 const den=1-b*b;
 if(Math.abs(den)<1e-5)return null;              // ось смотрит в камеру — тянуть нечем
 return(b*e-d)/den;}

// ---------------------------------------------------------------- гизмо осей
const AXES=[{n:"X",v:[1,0,0],c:"#ff5f5f",t:"вбок"},
            {n:"Y",v:[0,1,0],c:"#5fd46a",t:"вперёд/назад"},
            {n:"Z",v:[0,0,1],c:"#5fa8ff",t:"вверх/вниз"}];
let axisLock=null;                                // постоянное ограничение (клавиши X/Y/Z)
let tool="move";                                  // "move" — стрелки, "rot" — кольца
const HGT=P.bounds.hi[2]-P.bounds.lo[2];
// ---- гизмо вращения: три кольца по мировым осям вокруг НАЧАЛА кости ----
function planeBasis(A){
 let b1=Math.abs(A[0])<0.9?[1,0,0]:[0,1,0];
 b1=[A[1]*b1[2]-A[2]*b1[1],A[2]*b1[0]-A[0]*b1[2],A[0]*b1[1]-A[1]*b1[0]];
 const l=Math.hypot(...b1)||1;b1=b1.map(v=>v/l);
 const b2=[A[1]*b1[2]-A[2]*b1[1],A[2]*b1[0]-A[0]*b1[2],A[0]*b1[1]-A[1]*b1[0]];
 return[b1,b2];}
function rotGizmo(P0){
 if(!ACT||!P0)return null;
 const pj=projIn(P0,ACT.vp,ACT.rect);if(!pj)return null;
 const d=window.devicePixelRatio||1,RAD=62*d,PR=0.09*HGT;
 // масштаб берём по наименее сплющенной оси, иначе в косом ракурсе кольца крошечные
 let scale=0;
 for(const a of AXES){
  const p1=projIn([P0[0]+a.v[0]*PR,P0[1]+a.v[1]*PR,P0[2]+a.v[2]*PR],ACT.vp,ACT.rect);
  if(p1)scale=Math.max(scale,Math.hypot(p1[0]-pj[0],p1[1]-pj[1])/PR);}
 const R=scale>1e-6?RAD/scale:PR;
 const e=camPos(ACT.dir);
 let vd=[e[0]-P0[0],e[1]-P0[1],e[2]-P0[2]];
 const vl=Math.hypot(...vd)||1;vd=vd.map(v=>v/vl);
 const rings=AXES.map(a=>{
  const[b1,b2]=planeBasis(a.v),pts=[];
  for(let k=0;k<=56;k++){const t=k/56*Math.PI*2,c=Math.cos(t),s=Math.sin(t);
   const q=projIn([P0[0]+R*(b1[0]*c+b2[0]*s),P0[1]+R*(b1[1]*c+b2[1]*s),
                   P0[2]+R*(b1[2]*c+b2[2]*s)],ACT.vp,ACT.rect);
   if(q)pts.push(q);}
  return{a,b1,b2,pts,edge:Math.abs(a.v[0]*vd[0]+a.v[1]*vd[1]+a.v[2]*vd[2])<0.20};});
 return{P:P0,pj,R,rings};}
function drawRotGizmo(P0){
 const g=rotGizmo(P0);if(!g)return;
 const d=window.devicePixelRatio||1;
 for(const r of g.rings){
  if(r.pts.length<3)continue;
  const on=drag&&drag.rot&&drag.rot.axis.n===r.a.n;
  oc.strokeStyle=r.edge?"rgba(150,155,165,.30)":r.a.c;
  oc.lineWidth=(on?4.5:2.2)*d;
  oc.beginPath();oc.moveTo(r.pts[0][0],r.pts[0][1]);
  for(let i=1;i<r.pts.length;i++)oc.lineTo(r.pts[i][0],r.pts[i][1]);
  oc.stroke();
  if(r.edge)continue;
  const m=r.pts[Math.floor(r.pts.length*0.13)];
  oc.fillStyle=r.a.c;oc.font="600 "+(11*d)+"px Segoe UI";oc.fillText(r.a.n,m[0]+6*d,m[1]-6*d);}
 oc.fillStyle="#6fd1ff";oc.beginPath();oc.arc(g.pj[0],g.pj[1],3.5*d,0,7);oc.fill();
 if(drag&&drag.rot&&drag.rot.deg!==undefined){
  oc.fillStyle="#dfe3e8";oc.font="600 "+(13*d)+"px Segoe UI";
  oc.fillText(drag.rot.deg.toFixed(1)+"°",g.pj[0]+12*d,g.pj[1]-12*d);}}
function hitRot(mx,my,P0){
 const g=rotGizmo(P0);if(!g)return null;
 const d=window.devicePixelRatio||1;let best=null,bd=12*d;
 for(const r of g.rings){if(r.edge)continue;
  for(let i=1;i<r.pts.length;i++){
   const dd=segDist(mx,my,r.pts[i-1][0],r.pts[i-1][1],r.pts[i][0],r.pts[i][1]);
   if(dd<bd){bd=dd;best=r;}}}
 return best;}
function ringAngle(v,mx,my,P0,r){
 const{n,u}=mouseRay(v,mx,my),A=r.a.v;
 const den=u[0]*A[0]+u[1]*A[1]+u[2]*A[2];
 if(Math.abs(den)>0.06){
  const t=((P0[0]-n[0])*A[0]+(P0[1]-n[1])*A[1]+(P0[2]-n[2])*A[2])/den;
  const p=[n[0]+u[0]*t-P0[0],n[1]+u[1]*t-P0[1],n[2]+u[2]*t-P0[2]];
  return Math.atan2(p[0]*r.b2[0]+p[1]*r.b2[1]+p[2]*r.b2[2],
                    p[0]*r.b1[0]+p[1]*r.b1[1]+p[2]*r.b1[2]);}
 const pj=projIn(P0,v.vp,v.rect);
 return pj?Math.atan2(my-pj[1],mx-pj[0]):null;}
function gizmo(){
 if(selBone<0||!ACT)return null;
 evalPose(pose);
 const J=tail(selBone),pj=projIn(J,ACT.vp,ACT.rect);
 if(!pj)return null;
 const d=window.devicePixelRatio||1,LEN=60*d,PROBE=0.1;
 const arms=AXES.map(a=>{
  const p=projIn([J[0]+a.v[0]*PROBE,J[1]+a.v[1]*PROBE,J[2]+a.v[2]*PROBE],ACT.vp,ACT.rect);
  if(!p)return null;
  const L=Math.hypot(p[0]-pj[0],p[1]-pj[1]);
  if(L<1e-3)return{a,tip:pj,flat:true};
  const k=PROBE*LEN/L;
  const tip=projIn([J[0]+a.v[0]*k,J[1]+a.v[1]*k,J[2]+a.v[2]*k],ACT.vp,ACT.rect);
  return tip?{a,tip,flat:L*10<LEN*0.22,off:[0,0]}:null;});  // почти вдоль взгляда — не тянем
 // В фас мировые Y и Z обе идут по экрану вертикально и накладываются друг на друга —
 // такие пары разводим в стороны, иначе по нужной оси не попасть мышью.
 const dir=arms.map(a=>{if(!a||a.flat)return null;
  const dx=a.tip[0]-pj[0],dy=a.tip[1]-pj[1],L=Math.hypot(dx,dy)||1;return[dx/L,dy/L];});
 for(let i=0;i<3;i++)for(let j=i+1;j<3;j++){
  if(!dir[i]||!dir[j])continue;
  if(Math.abs(dir[i][0]*dir[j][1]-dir[i][1]*dir[j][0])>0.20)continue;
  const p=[-dir[i][1],dir[i][0]],k=9*d;
  arms[i].off=[p[0]*k,p[1]*k];arms[j].off=[-p[0]*k,-p[1]*k];}
 return{J,pj,arms};}
const armSeg=(g,arm)=>[g.pj[0]+arm.off[0],g.pj[1]+arm.off[1],
                       arm.tip[0]+arm.off[0],arm.tip[1]+arm.off[1]];
function segDist(px,py,x1,y1,x2,y2){
 const dx=x2-x1,dy=y2-y1,L=dx*dx+dy*dy;
 let t=L?((px-x1)*dx+(py-y1)*dy)/L:0;t=Math.max(0,Math.min(1,t));
 return Math.hypot(px-(x1+dx*t),py-(y1+dy*t));}
function hitAxis(mx,my){
 const g=gizmo();if(!g)return null;
 const d=window.devicePixelRatio||1;let best=null,bd=11*d;
 for(const arm of g.arms){if(!arm||arm.flat)continue;
  const s=armSeg(g,arm);
  const dd=segDist(mx,my,s[0],s[1],s[2],s[3]);
  if(dd<bd){bd=dd;best=arm.a;}}
 return best;}
function drawGizmo(){
 if(tool==="rot"){if(selBone>=0){evalPose(pose);drawRotGizmo(head(selBone));}return;}
 const g=gizmo();if(!g)return;
 const d=window.devicePixelRatio||1;
 for(const arm of g.arms){if(!arm)continue;
  const on=(drag&&drag.axis&&drag.axis.n===arm.a.n)||axisLock===arm.a.n;
  const s=armSeg(g,arm);
  oc.strokeStyle=arm.flat?"rgba(150,155,165,.28)":arm.a.c;
  oc.lineWidth=(on?4.5:2.5)*d;
  oc.beginPath();oc.moveTo(s[0],s[1]);oc.lineTo(s[2],s[3]);oc.stroke();
  if(arm.flat)continue;
  oc.fillStyle=arm.a.c;
  oc.beginPath();oc.arc(s[2],s[3],(on?6.5:5)*d,0,7);oc.fill();
  oc.font="600 "+(11*d)+"px Segoe UI";
  oc.fillText(arm.a.n,s[2]+8*d,s[3]-7*d);}}
function mulv(m,v){const o=[0,0,0,0];
 for(let r=0;r<4;r++){let s=0;for(let k=0;k<4;k++)s+=m[k*4+r]*v[k];o[r]=s;}return o;}

// ---------------------------------------------------------------- зеркало
function mirrorPose(){
 evalPose(pose);
 const tw=[];
 for(const i of ORDER){const n=NAMES[i];
  let src=i;
  if(n.endsWith(".L"))src=IDX[n.slice(0,-2)+".R"];
  else if(n.endsWith(".R"))src=IDX[n.slice(0,-2)+".L"];
  const q=wQ[src];tw[i]=[q[0],q[1],-q[2],-q[3]];}
 const np=newPose();np.loc=[-pose.loc[0],pose.loc[1],pose.loc[2]];
 for(const i of ORDER){const p=B[i].parent;
  const bq=p<0?relQ[i]:qmul(tw[p],relQ[i]);
  np.q[i]=qnorm(qmul(qcon(bq),tw[i]));}
 pose=np;commit();ui();draw();}

// ---------------------------------------------------------------- UI
function ui(){
 document.getElementById("selName").textContent=selBone>=0?NAMES[selBone]:"—";
 const bl=document.getElementById("blist");
 bl.innerHTML=NAMES.map((n,i)=>`<div class="bi${i===selBone?" sel":""}${B[i].deform?"":" ctl"}" data-i="${i}">${n}</div>`).join("");
 bl.querySelectorAll(".bi").forEach(el=>el.onclick=()=>{selBone=+el.dataset.i;ui();draw();});
 const tl=document.getElementById("tl");
 let h="";
 for(let f=1;f<=clip.length;f++)
  h+=`<div class="fr${f===frame?" cur":""}${clip.keys[f]?" key":""}" data-f="${f}">
      ${clip.keys[f]?'<div class="d"></div>':''}${f%5===0||f===1?f:""}</div>`;
 tl.innerHTML=h;
 tl.querySelectorAll(".fr").forEach(el=>el.onclick=()=>setFrame(+el.dataset.f));
 document.getElementById("info").innerHTML=
  `кадр ${frame} из ${clip.length} · ключей ${keyFrames().length}<br>`+
  `костей ${NB} · вершин ${P.counts.verts} · треугольников ${P.counts.tris}`;
 document.getElementById("clipName").value=clip.name;
 document.getElementById("clipLen").value=clip.length;
 document.getElementById("fps").value=clip.fps;
}
function loadClip(n){clip=clips[n];frame=1;pose=poseAt(1);
 const s=document.getElementById("clipSel");
 s.innerHTML=Object.keys(clips).map(k=>`<option${k===n?" selected":""}>${k}</option>`).join("");
 ui();draw();}
document.getElementById("clipSel").onchange=e=>loadClip(e.target.value);
document.getElementById("clipName").onchange=e=>{
 const old=clip.name,nn=e.target.value.trim()||old;
 delete clips[old];clip.name=nn;clips[nn]=clip;loadClip(nn);};
document.getElementById("clipLen").onchange=e=>{clip.length=Math.max(2,+e.target.value);setFrame(frame);};
document.getElementById("fps").onchange=e=>{clip.fps=Math.max(1,+e.target.value);};
document.getElementById("bKey").onclick=()=>{commit();ui();draw();};
document.getElementById("bDelKey").onclick=()=>{if(keyFrames().length>1){delete clip.keys[frame];setFrame(frame);}};
document.getElementById("bCopy").onclick=()=>{clipboard=clonePose(pose);};
document.getElementById("bPaste").onclick=()=>{if(clipboard){pose=clonePose(clipboard);commit();ui();draw();}};
document.getElementById("bMirror").onclick=mirrorPose;
document.getElementById("bReset").onclick=()=>{if(selBone>=0){pose.q[selBone]=[1,0,0,0];commit();draw();}};
document.getElementById("bRestAll").onclick=()=>{pose=newPose();commit();ui();draw();};
document.getElementById("bLoop").onclick=()=>{
 const k=clip.keys[1];if(k){clip.keys[clip.length]=clonePose(k);ui();draw();}};
for(const b of document.querySelectorAll("[data-cam]"))b.onclick=()=>{
 const m={front:[0,0.05],side:[Math.PI/2,0.05],q34:[0.9,0.15],top:[0,1.3]}[b.dataset.cam];
 C.az=m[0];C.el=m[1];draw();};
// ---- ограничение по оси ----
function axisUI(){
 const a=axisLock?AXES.find(x=>x.n===axisLock):null;
 const el=document.getElementById("axv");
 el.textContent=a?(a.n+" — "+a.t):"свободно";
 el.style.color=a?a.c:"var(--dim)";
 for(const b of document.querySelectorAll("[data-ax]"))
  b.classList.toggle("on",(b.dataset.ax||null)===axisLock);}
for(const b of document.querySelectorAll("[data-ax]"))
 b.onclick=()=>{axisLock=b.dataset.ax||null;axisUI();draw();};
axisUI();
// ---- эталон из игры ----
refDir.innerHTML=REF.dirs.map(d=>`<option${d===RS.dir?" selected":""}>${d}</option>`).join("");
refBlock.onchange=e=>{RS.block=e.target.value;
 if(RS.block){const n=REF.blocks[RS.block].frames;
  document.getElementById("hint").textContent=
   "эталон: "+RS.block+", "+n+" кадров · камера игры (наклон "+REF.tilt.toFixed(2)+"°, азимут "+
   REF.az[RS.dir]+"°) · ЛКМ по точке — тянуть";}
 draw();};
refDir.onchange=e=>{RS.dir=e.target.value;draw();};
refOp.oninput=e=>{RS.op=+e.target.value/100;refOpV.textContent=e.target.value+"%";draw();};
refZoom.oninput=e=>{RS.zoom=+e.target.value/10;refZoomV.textContent="×"+RS.zoom.toFixed(1);draw();};
refDy.oninput=e=>{RS.dy=+e.target.value;refDyV.textContent=RS.dy+" px";draw();};
bDy0.onclick=()=>{RS.dy=0;refDy.value=0;refDyV.textContent="0 px";draw();};
bGrid.onclick=()=>{RS.grid=!RS.grid;bGrid.classList.toggle("on",RS.grid);
 if(RS.grid&&RS.zoom>2)  {RS.zoom=1.6;refZoom.value=16;refZoomV.textContent="×1.6";}
 if(!RS.grid&&RS.zoom<2.5){RS.zoom=3;  refZoom.value=30;refZoomV.textContent="×3.0";}
 draw();};
bIso.onclick=()=>{RS.iso=!RS.iso;bIso.classList.toggle("on",RS.iso);draw();};
bDiff.onclick=()=>{RS.diff=!RS.diff;bDiff.classList.toggle("on",RS.diff);
 if(RS.diff){RS.front=false;bRefFront.classList.remove("on");}draw();};
bRefFront.onclick=()=>{RS.front=!RS.front;bRefFront.classList.toggle("on",RS.front);
 if(RS.front){RS.diff=false;bDiff.classList.remove("on");}draw();};
bFit.onclick=()=>{if(!RS.block)return;
 clip.length=REF.blocks[RS.block].frames;setFrame(Math.min(frame,clip.length));};
tMove.onclick=()=>{tool="move";tMove.classList.add("on");tRot.classList.remove("on");draw();};
tRot.onclick=()=>{tool="rot";tRot.classList.add("on");tMove.classList.remove("on");draw();};
document.getElementById("mIK").onclick=()=>{mIK.classList.add("on");mFK.classList.remove("on");};
document.getElementById("mFK").onclick=()=>{mFK.classList.add("on");mIK.classList.remove("on");};
function twistBy(deg){if(selBone<0)return;
 withHold(selBone,()=>{evalPose(pose);
  const ax=qrot(wQ[selBone],[0,1,0]);
  applyWorld(pose,selBone,qaxis(ax,deg*Math.PI/180));});
 commit();draw();}
document.getElementById("bOnly").onclick=()=>{
 document.getElementById("chain").value=1;
 const h=document.getElementById("cHold");h.checked=true;
 draw();};
document.getElementById("cHold").onchange=draw;
document.getElementById("twistR").oninput=e=>{
 const v=+e.target.value,prev=+document.getElementById("twist").value;
 document.getElementById("twist").value=v;twistBy(v-prev);};
document.getElementById("twist").onchange=e=>{
 const v=+e.target.value;document.getElementById("twistR").value=v;};
document.addEventListener("keydown",e=>{
 if(/INPUT|SELECT/.test(document.activeElement.tagName))return;
 const ax={x:"X",y:"Y",z:"Z",ч:"X",н:"Y",я:"Z"}[e.key.toLowerCase()];
 if(ax){axisLock=(axisLock===ax)?null:ax;axisUI();draw();e.preventDefault();return;}
 if(e.key==="Escape"){axisLock=null;axisUI();draw();return;}
 if(e.key==="q"||e.key==="Q"){twistBy(-6);e.preventDefault();}
 if(e.key==="e"||e.key==="E"){twistBy(6);e.preventDefault();}
 if(e.key==="ArrowRight"){setFrame(frame+1);e.preventDefault();}
 if(e.key==="ArrowLeft"){setFrame(frame-1);e.preventDefault();}
 if(e.key===" "){play();e.preventDefault();}});
let last=0,acc=0;
function play(){playing=!playing;document.getElementById("bPlay").textContent=playing?"⏸ пауза":"▶ играть";
 last=performance.now();if(playing)requestAnimationFrame(tick);}
document.getElementById("bPlay").onclick=play;
function tick(t){if(!playing)return;
 acc+=(t-last)/1000;last=t;
 const step=1/clip.fps;
 while(acc>=step){acc-=step;frame=frame>=clip.length?1:frame+1;}
 pose=poseAt(frame);ui();draw();requestAnimationFrame(tick);}
document.getElementById("cOnion").onchange=document.getElementById("cBones").onchange=
 document.getElementById("cMesh").onchange=draw;
document.getElementById("bExport").onclick=()=>{
 const o={name:clip.name,fps:clip.fps,length:clip.length,bones:NAMES,
  keys:Object.fromEntries(keyFrames().map(f=>[f,{q:clip.keys[f].q.map(q=>q.map(v=>+v.toFixed(6))),
   loc:clip.keys[f].loc.map(v=>+v.toFixed(6))}]))};
 const b=new Blob([JSON.stringify(o)],{type:"application/json"});
 const a=document.createElement("a");a.href=URL.createObjectURL(b);
 a.download=clip.name.replace(/[^\w\-]+/g,"_")+".json";a.click();};
document.getElementById("bImport").onclick=()=>{
 const inp=document.createElement("input");inp.type="file";inp.accept=".json";
 inp.onchange=()=>{const fr=new FileReader();
  fr.onload=()=>{try{const o=JSON.parse(fr.result);
    const keys={};for(const f in o.keys)keys[f]={q:o.keys[f].q.map(v=>v.slice()),loc:o.keys[f].loc.slice()};
    clips[o.name]={name:o.name,fps:o.fps||24,length:o.length,keys};loadClip(o.name);}
   catch(err){alert("не читается: "+err.message);}};
  fr.readAsText(inp.files[0]);};
 inp.click();};
window.addEventListener("resize",draw);
loadClip(Object.keys(clips)[0]);
window.__ready=true;
</script></body></html>
"""

REFPAYLOAD = os.path.join(ROOT, "tools", "webanim", "refpayload.json")
payload = open(PAYLOAD, encoding="utf-8").read()
ref = open(REFPAYLOAD, encoding="utf-8").read() if os.path.exists(REFPAYLOAD) else \
    '{"blocks":{},"dirs":[],"az":{},"window":{"w":1,"h":1,"ax":0,"ay":0},' \
    '"tilt":33.48,"px_per_unit":46.01}'
open(DEST, "w", encoding="utf-8").write(
    HTML.replace("__PAYLOAD__", payload).replace("__REFPAYLOAD__", ref))
print("записано %s  %.2f MB" % (DEST, os.path.getsize(DEST) / 1024 / 1024))
