"""Собирает character_studio.html — мастерская персонажа целиком в браузере.

    python tools/make_studio.py

Страница ничего не содержит от конкретного героя: модель грузится пользователем.
Внутрь вшивается только эталон движений из игры (tools/webanim/refpayload.json),
он от персонажа не зависит.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFP = os.path.join(ROOT, "tools", "webanim", "refpayload.json")
DEST = os.path.join(ROOT, "character_studio.html")

HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Князь 2 — мастерская персонажа</title>
<style>
:root{--bg:#15171a;--pan:#1e2126;--line:#31363d;--txt:#dfe3e8;--dim:#8b939e;--acc:#e0a458;--sel:#6fd1ff;--ok:#7fd18a}
*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--txt);
 font:13px/1.45 "Segoe UI",system-ui,sans-serif}
#app{display:flex;flex-direction:column;height:100%}
header{display:flex;gap:8px;align-items:center;padding:7px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
h1{font-size:14px;margin:0 8px 0 0;font-weight:600;white-space:nowrap}
button,select,input[type=text],input[type=number]{background:#2a2f36;color:var(--txt);
 border:1px solid var(--line);border-radius:5px;padding:4px 9px;font:inherit}
button{cursor:pointer}button:hover{background:#343a43}
button:disabled{opacity:.4;cursor:not-allowed}
button.on{background:var(--acc);color:#16181b;border-color:var(--acc)}
button.pri{background:#2f6d46;border-color:#3c8a59}
.step{display:flex;align-items:center;gap:6px;padding:4px 10px;border-radius:15px;
 border:1px solid var(--line);color:var(--dim);cursor:pointer;user-select:none}
.step.act{border-color:var(--sel);color:var(--sel)}
.step.done{border-color:#3c8a59;color:var(--ok)}
.step b{font-weight:600}
label.chk{display:inline-flex;gap:5px;align-items:center;cursor:pointer;user-select:none;color:var(--dim)}
main{flex:1;display:flex;min-height:0}
#view{flex:1;position:relative;min-width:0;background:#0d0f11}
canvas#bg{position:absolute;inset:0;pointer-events:none;image-rendering:pixelated}
canvas#gl{display:block;width:100%;height:100%;position:relative}
canvas#ov{position:absolute;inset:0;pointer-events:none}
#drop{position:absolute;inset:24px;border:2px dashed #3a4150;border-radius:14px;
 display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;
 color:var(--dim);text-align:center;background:rgba(21,23,26,.6)}
#drop.hide{display:none}
#drop b{color:var(--txt);font-size:16px}
#hint{position:absolute;left:10px;bottom:8px;color:var(--dim);font-size:11px;
 background:rgba(21,23,26,.78);padding:4px 8px;border-radius:4px;pointer-events:none;max-width:70%}
aside{width:288px;border-left:1px solid var(--line);background:var(--pan);padding:10px;overflow:auto}
aside h3{margin:12px 0 6px;font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
aside h3:first-child{margin-top:0}
.row{display:flex;gap:6px;align-items:center;margin:5px 0}
.row span{color:var(--dim);flex:1}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:5px}
.blist{max-height:180px;overflow:auto;border:1px solid var(--line);border-radius:5px}
.bi{padding:2px 7px;cursor:pointer;border-radius:3px}
.bi:hover{background:#262b32}.bi.sel{background:#2f3a44;outline:1px solid var(--sel)}
.bi.ctl{color:var(--dim)}
input[type=range]{width:100%}
table.st{width:100%;border-collapse:collapse;font-size:12px}
table.st td{padding:2px 4px;border-bottom:1px solid #262a30}
table.st td:last-child{text-align:right;font-family:ui-monospace,Consolas,monospace}
.ok{color:var(--ok)}.warn{color:var(--acc)}
#fail{position:fixed;left:0;right:0;top:0;z-index:99;display:none;
 background:#4a1e1e;border-bottom:1px solid #8a3030;color:#ffd0d0;padding:8px 14px;
 font:12px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;max-height:45vh;overflow:auto}
#fail b{color:#fff}
#busy{position:absolute;inset:0;background:rgba(13,15,17,.82);display:none;
 align-items:center;justify-content:center;flex-direction:column;gap:10px;font-size:15px}
#busy.on{display:flex}
</style></head><body><div id="app">
<header>
  <h1>Мастерская персонажа</h1>
  <div class="step act" data-step="0"><b>1</b> модель</div>
  <div class="step" data-step="1"><b>2</b> скелет</div>
  <div class="step" data-step="2"><b>3</b> привязка</div>
  <div class="step" data-step="3"><b>4</b> поза</div>
  <div class="step" data-step="4"><b>5</b> спрайты</div>
  <span style="flex:1"></span>
  <label class="chk"><input type="checkbox" id="cMesh" checked> модель</label>
  <label class="chk"><input type="checkbox" id="cBones" checked> скелет</label>
  <label class="chk"><input type="checkbox" id="cTex"> текстура</label>
</header>
<main>
  <div id="view">
    <canvas id="bg"></canvas><canvas id="gl"></canvas><canvas id="ov"></canvas>
    <div id="drop"><b>Перетащи сюда .glb</b>
      <div>можно добавить картинку текстуры вторым файлом</div>
      <div><input type="file" id="file" accept=".glb,.png,.jpg,.jpeg" multiple></div></div>
    <div id="hint">ПКМ — вращать вид · колесо — зум · Shift+ПКМ — сдвиг</div>
    <div id="busy"><div id="busytx">…</div></div>
  </div>
  <aside id="panel"></aside>
</main></div>
<div id="fail"></div>
<script>
// Любой сбой должен быть ВИДЕН. Молчаливо падающая страница выглядит как «не
// работает», и причину приходится угадывать.
function showFail(msg){
 const el=document.getElementById("fail");
 if(!el)return;
 el.style.display="block";
 el.innerHTML+=(el.innerHTML?"\n":"")+"<b>сбой:</b> "+String(msg).replace(/[<>&]/g,
   c=>({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]));}
window.addEventListener("error",e=>showFail(
  e.message+"  ("+(e.filename||"").split("/").pop()+":"+e.lineno+":"+e.colno+")"));
window.addEventListener("unhandledrejection",e=>showFail(
  "необработанный отказ: "+((e.reason&&e.reason.message)||e.reason)));
const REF = __REFPAYLOAD__;
const POSELIB = __POSELIB__;
// ============================================================ математика
const qmul=(a,b)=>[a[0]*b[0]-a[1]*b[1]-a[2]*b[2]-a[3]*b[3],
 a[0]*b[1]+a[1]*b[0]+a[2]*b[3]-a[3]*b[2],
 a[0]*b[2]-a[1]*b[3]+a[2]*b[0]+a[3]*b[1],
 a[0]*b[3]+a[1]*b[2]-a[2]*b[1]+a[3]*b[0]];
const qcon=q=>[q[0],-q[1],-q[2],-q[3]];
const qnorm=q=>{const l=Math.hypot(q[0],q[1],q[2],q[3])||1;return q.map(v=>v/l);};
const qrot=(q,v)=>{const t=[2*(q[2]*v[2]-q[3]*v[1]),2*(q[3]*v[0]-q[1]*v[2]),2*(q[1]*v[1]-q[2]*v[0])];
 return[v[0]+q[0]*t[0]+q[2]*t[2]-q[3]*t[1],v[1]+q[0]*t[1]+q[3]*t[0]-q[1]*t[2],
        v[2]+q[0]*t[2]+q[1]*t[1]-q[2]*t[0]];};
const qaxis=(ax,an)=>{const s=Math.sin(an/2);return[Math.cos(an/2),ax[0]*s,ax[1]*s,ax[2]*s];};
function qfromto(a,b){const d=a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
 if(d>0.999999)return[1,0,0,0];
 if(d<-0.999999){const o=Math.abs(a[0])<0.9?[1,0,0]:[0,1,0];
  const c=[a[1]*o[2]-a[2]*o[1],a[2]*o[0]-a[0]*o[2],a[0]*o[1]-a[1]*o[0]];
  const l=Math.hypot(...c)||1;return[0,c[0]/l,c[1]/l,c[2]/l];}
 const c=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
 return qnorm([1+d,c[0],c[1],c[2]]);}
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
 return new Float32Array([t/a,0,0,0,0,t,0,0,0,0,(fa+n)/(n-fa),-1,0,0,2*fa*n/(n-fa),0]);}
function ortho(w,h,n,f,ox,oy){
 return new Float32Array([2/w,0,0,0,0,2/h,0,0,0,0,-2/(f-n),0,ox,oy,-(f+n)/(f-n),1]);}
function lookAt(e,c,u){let z=[e[0]-c[0],e[1]-c[1],e[2]-c[2]];let l=Math.hypot(...z)||1;z=z.map(v=>v/l);
 let x=[u[1]*z[2]-u[2]*z[1],u[2]*z[0]-u[0]*z[2],u[0]*z[1]-u[1]*z[0]];l=Math.hypot(...x)||1;x=x.map(v=>v/l);
 const y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]];
 return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,
  -(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]),-(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]),-(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]),1]);}
function invMat(m){const a=[...m],inv=new Float64Array(16);
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
 let d=a[0]*inv[0]+a[1]*inv[4]+a[2]*inv[8]+a[3]*inv[12];d=d?1/d:0;
 for(let i=0;i<16;i++)inv[i]*=d;return inv;}
const mulv=(m,v)=>{const o=[0,0,0,0];
 for(let r=0;r<4;r++){let s=0;for(let k=0;k<4;k++)s+=m[k*4+r]*v[k];o[r]=s;}return o;};
function segDistSq(p,a,b){
 const dx=b[0]-a[0],dy=b[1]-a[1],dz=b[2]-a[2];
 const L=dx*dx+dy*dy+dz*dz;
 let t=L?((p[0]-a[0])*dx+(p[1]-a[1])*dy+(p[2]-a[2])*dz)/L:0;
 t=t<0?0:t>1?1:t;
 const ex=p[0]-(a[0]+dx*t),ey=p[1]-(a[1]+dy*t),ez=p[2]-(a[2]+dz*t);
 return ex*ex+ey*ey+ez*ez;}

// ============================================================ разбор GLB
function parseGLB(buf){
 const dv=new DataView(buf);
 if(dv.getUint32(0,true)!==0x46546C67)throw new Error("это не .glb");
 let off=12,json=null,bin=null;
 while(off<dv.byteLength){
  const len=dv.getUint32(off,true),type=dv.getUint32(off+4,true);
  const data=buf.slice(off+8,off+8+len);
  if(type===0x4E4F534A)json=JSON.parse(new TextDecoder().decode(data));
  else if(type===0x004E4942)bin=data;
  off+=8+len+((4-len%4)%4===4?0:0);
  off+=(4-(len%4))%4;}
 if(!json)throw new Error("в файле нет JSON-куска");
 const CT={5120:Int8Array,5121:Uint8Array,5122:Int16Array,5123:Uint16Array,
           5125:Uint32Array,5126:Float32Array};
 // MAT4 обязателен: обратные матрицы привязки приходят именно им, и без него
 // массив выходит пустым, а все скин-матрицы — NaN
 const NC={SCALAR:1,VEC2:2,VEC3:3,VEC4:4,MAT2:4,MAT3:9,MAT4:16};
 const acc=i=>{
  const a=json.accessors[i],bv=json.bufferViews[a.bufferView];
  const T=CT[a.componentType],n=NC[a.type],cnt=a.count;
  const base=(bv.byteOffset||0)+(a.byteOffset||0);
  const stride=bv.byteStride;
  if(stride&&stride!==n*T.BYTES_PER_ELEMENT){
   const out=new T(cnt*n),src=new Uint8Array(bin,base,stride*cnt);
   const tmp=new Uint8Array(out.buffer);
   for(let k=0;k<cnt;k++)tmp.set(src.subarray(k*stride,k*stride+n*T.BYTES_PER_ELEMENT),
                                k*n*T.BYTES_PER_ELEMENT);
   return out;}
  return new T(bin,base,cnt*n);};
 // берём все примитивы всех мешей и склеиваем
 let pos=[],nor=[],uv=[],idx=[],base=0;
 for(const m of json.meshes||[])for(const pr of m.primitives){
  const P=acc(pr.attributes.POSITION);
  const N=pr.attributes.NORMAL!==undefined?acc(pr.attributes.NORMAL):null;
  const U=pr.attributes.TEXCOORD_0!==undefined?acc(pr.attributes.TEXCOORD_0):null;
  const I=pr.indices!==undefined?acc(pr.indices):null;
  const n=P.length/3;
  for(let i=0;i<n*3;i++)pos.push(P[i]);
  for(let i=0;i<n*3;i++)nor.push(N?N[i]:0);
  for(let i=0;i<n*2;i++)uv.push(U?U[i]:0);
  if(I)for(let i=0;i<I.length;i++)idx.push(base+I[i]);
  else for(let i=0;i<n;i++)idx.push(base+i);
  base+=n;}
 if(!pos.length)throw new Error("в файле нет геометрии");
 // glTF Y-вверх -> наши оси Z-вверх
 const V=new Float32Array(pos.length),NN=new Float32Array(nor.length);
 for(let i=0;i<pos.length;i+=3){
  V[i]=pos[i];V[i+1]=-pos[i+2];V[i+2]=pos[i+1];
  NN[i]=nor[i];NN[i+1]=-nor[i+2];NN[i+2]=nor[i+1];}
 // ---- скелет и скиннинг, если они в файле есть ----
 let skin=null;
 if(json.skins&&json.skins.length&&json.meshes){
  const sk=json.skins[0];
  const pr0=json.meshes[0].primitives[0];
  if(pr0.attributes.JOINTS_0!==undefined&&pr0.attributes.WEIGHTS_0!==undefined){
   const JA=acc(pr0.attributes.JOINTS_0),WA=acc(pr0.attributes.WEIGHTS_0);
   const wAcc=json.accessors[pr0.attributes.WEIGHTS_0];
   const nv=JA.length/4;
   const si=new Uint8Array(nv*4),sw=new Uint8Array(nv*4);
   const wsc=wAcc.componentType===5126?255:
             (wAcc.componentType===5121?1:255/65535);
   for(let i=0;i<nv*4;i++){
    si[i]=Math.min(255,JA[i]);
    sw[i]=Math.max(0,Math.min(255,Math.round(WA[i]*wsc)));}
   // нормируем на случай, если сумма не 255
   for(let v=0;v<nv;v++){let s=0;
    for(let k=0;k<4;k++)s+=sw[v*4+k];
    if(s>0&&s!==255)for(let k=0;k<4;k++)sw[v*4+k]=Math.round(sw[v*4+k]*255/s);}
   const ibm=sk.inverseBindMatrices!==undefined?acc(sk.inverseBindMatrices):null;
   // глобальные матрицы узлов
   const N=json.nodes||[];
   const local=i=>{const n=N[i];
    if(n.matrix)return n.matrix.slice();
    const t=n.translation||[0,0,0],r=n.rotation||[0,0,0,1],s=n.scale||[1,1,1];
    const[x,y,z,w]=r;
    const m=[(1-2*(y*y+z*z))*s[0],(2*(x*y+z*w))*s[0],(2*(x*z-y*w))*s[0],0,
             (2*(x*y-z*w))*s[1],(1-2*(x*x+z*z))*s[1],(2*(y*z+x*w))*s[1],0,
             (2*(x*z+y*w))*s[2],(2*(y*z-x*w))*s[2],(1-2*(x*x+y*y))*s[2],0,
             t[0],t[1],t[2],1];
    return m;};
   const mul=(a,b)=>{const o=new Array(16);
    for(let c=0;c<4;c++)for(let r=0;r<4;r++){let s=0;
     for(let k=0;k<4;k++)s+=a[k*4+r]*b[c*4+k];o[c*4+r]=s;}return o;};
   const parentOf=new Int32Array(N.length).fill(-1);
   N.forEach((n,i)=>(n.children||[]).forEach(c=>parentOf[c]=i));
   const glob=new Array(N.length).fill(null);
   const gl_=i=>{if(glob[i])return glob[i];
    const p=parentOf[i];
    glob[i]=p<0?local(i):mul(gl_(p),local(i));return glob[i];};
   skin={joints:sk.joints.slice(),parentOf,names:N.map((n,i)=>n.name||("node"+i)),
         global:sk.joints.map(j=>gl_(j)),
         ibm:ibm?Array.from({length:sk.joints.length},(_,k)=>
              Array.from(ibm.subarray(k*16,k*16+16))):null,
         si,sw};}}
 let img=null;
 if(json.images&&json.images.length){
  const im=json.images[0];
  if(im.bufferView!==undefined){
   const bv=json.bufferViews[im.bufferView];
   img=new Blob([new Uint8Array(bin,bv.byteOffset||0,bv.byteLength)],
                {type:im.mimeType||"image/png"});}
  else if(im.uri&&im.uri.startsWith("data:"))img=im.uri;}
 return{pos:V,nor:NN,uv:new Float32Array(uv),idx:new Uint32Array(idx),img,skin,
        gen:(json.asset||{}).generator||"—"};}

// сварка совпадающих вершин: нужна и для сглаживания весов, и чтобы поверхность
// перестала быть россыпью островов по швам развёртки
function weld(pos,eps){
 const n=pos.length/3,map=new Int32Array(n),h=new Map();
 const q=1/eps;let m=0;
 const rep=[];
 for(let i=0;i<n;i++){
  const k=Math.round(pos[i*3]*q)+","+Math.round(pos[i*3+1]*q)+","+Math.round(pos[i*3+2]*q);
  let j=h.get(k);
  if(j===undefined){j=m++;h.set(k,j);rep.push(i);}
  map[i]=j;}
 const wp=new Float32Array(m*3);
 for(let j=0;j<m;j++){const i=rep[j];
  wp[j*3]=pos[i*3];wp[j*3+1]=pos[i*3+1];wp[j*3+2]=pos[i*3+2];}
 return{map,wpos:wp,count:m};}

// ============================================================ скелет
const CENTER=["ground","pelvis","spine1","spine2","neck_base","head_base","head_top"];
const SIDED=["shoulder","elbow","wrist","hand_tip","hip","knee","ankle","toe","toe_tip"];
const RU={ground:"опора",pelvis:"таз",spine1:"поясница",spine2:"низ груди",
 neck_base:"основание шеи",head_base:"основание головы",head_top:"макушка",
 shoulder:"плечо",elbow:"локоть",wrist:"запястье",hand_tip:"конец кисти",
 hip:"тазобедренный",knee:"колено",ankle:"лодыжка",toe:"носок",toe_tip:"кончик носка"};
const SPEC=[["root","ground","pelvis",null,false,false],
 ["spine_01","pelvis","spine1","root",true,true],
 ["spine_02","spine1","spine2","spine_01",true,true],
 ["chest","spine2","neck_base","spine_02",true,true],
 ["neck","neck_base","head_base","chest",true,true],
 ["head","head_base","head_top","neck",true,true]];
for(const s of ["L","R"]){
 SPEC.push(["clavicle."+s,"@clav"+s,"shoulder"+s,"chest",false,true],
  ["upper_arm."+s,"shoulder"+s,"elbow"+s,"clavicle."+s,true,true],
  ["forearm."+s,"elbow"+s,"wrist"+s,"upper_arm."+s,true,true],
  ["hand."+s,"wrist"+s,"hand_tip"+s,"forearm."+s,true,true],
  ["hip."+s,"pelvis","hip"+s,"root",false,true],
  ["thigh."+s,"hip"+s,"knee"+s,"hip."+s,true,true],
  ["shin."+s,"knee"+s,"ankle"+s,"thigh."+s,true,true],
  ["foot."+s,"ankle"+s,"toe"+s,"shin."+s,true,true],
  ["toe."+s,"toe"+s,"toe_tip"+s,"foot."+s,true,true]);}

let J={};                                   // суставы: ключ -> [x,y,z]
const jk=(n,s)=>s?n+s:n;
function jointPos(key){
 if(key.startsWith("@clav")){                // ключица начинается у основания шеи
  const s=key.slice(5),a=J["neck_base"],b=J["shoulder"+s],t=0.12;
  return[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t];}
 return J[key];}

// Первичная догадка по геометрии: рост и ступни из габаритов, плечо/локоть/запястье
// из профиля сечений вдоль руки, ноги — из центров сечений и анатомических долей.
function autoJoints(pos){
 const n=pos.length/3;
 let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9,z0=1e9,z1=-1e9;
 for(let i=0;i<n;i++){const x=pos[i*3],y=pos[i*3+1],z=pos[i*3+2];
  if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;if(z<z0)z0=z;if(z>z1)z1=z;}
 const H=z1-z0;
 const NB=64,bin=[];
 for(let k=0;k<NB;k++)bin.push({zmin:1e9,zmax:-1e9,ymin:1e9,ymax:-1e9,n:0});
 for(let i=0;i<n;i++){const x=pos[i*3];if(x<=0)continue;
  const k=Math.min(NB-1,Math.floor(x/x1*NB)),b=bin[k];
  const y=pos[i*3+1],z=pos[i*3+2];
  if(z<b.zmin)b.zmin=z;if(z>b.zmax)b.zmax=z;
  if(y<b.ymin)b.ymin=y;if(y>b.ymax)b.ymax=y;b.n++;}
 const bx=k=>(k+0.5)/NB*x1;
 let sh=-1;
 for(let k=2;k<NB;k++)if(bin[k].n>20&&bin[k].zmax-bin[k].zmin<0.30*H){sh=k;break;}
 if(sh<0)sh=Math.round(NB*0.18);
 const armZ=k=>(bin[k].zmin+bin[k].zmax)/2, armY=k=>(bin[k].ymin+bin[k].ymax)/2;
 let wr=sh,best=1e9;
 for(let k=sh+4;k<NB-3;k++){if(bin[k].n<10)continue;
  const c=(bin[k].zmax-bin[k].zmin)*(bin[k].ymax-bin[k].ymin);
  if(c<best){best=c;wr=k;}}
 const shX=bx(sh)*0.80, wrX=bx(wr);
 const elX=shX+(wrX-shX)*0.56;               // плечевая кость длиннее предплечья
 const at=x=>{const k=Math.min(NB-1,Math.max(0,Math.round(x/x1*NB-0.5)));
  return bin[k].n?[armZ(k),armY(k)]:[armZ(sh),armY(sh)];};
 // Высоту плеча берём из ПЕРВОГО «только рука» бина: у бина под shX сечение ещё
 // торсовое, от пят до головы, и его центр даёт плечо на середине тела.
 const [shZ,shY]=[armZ(sh),armY(sh)],[elZ,elY]=at(elX),[wrZ,wrY]=at(wrX);
 // торс: центр сечения по высоте
 const TB=40,tb=[];
 for(let k=0;k<TB;k++)tb.push({ymin:1e9,ymax:-1e9,xs:0,n:0});
 for(let i=0;i<n;i++){const x=pos[i*3];if(Math.abs(x)>0.16*H)continue;
  const k=Math.min(TB-1,Math.floor((pos[i*3+2]-z0)/H*TB)),b=tb[k];
  const y=pos[i*3+1];if(y<b.ymin)b.ymin=y;if(y>b.ymax)b.ymax=y;b.n++;}
 const ty=h=>{const k=Math.min(TB-1,Math.max(0,Math.round(h*TB-0.5)));
  return tb[k].n?(tb[k].ymin+tb[k].ymax)/2:0;};
 // ноги: центр по X ниже юбки
 let lx=0,lc=0;
 for(let i=0;i<n;i++){const z=pos[i*3+2],x=pos[i*3];
  const h=(z-z0)/H;if(h<0.12||h>0.26||x<=0)continue;lx+=x;lc++;}
 const legX=lc?lx/lc:0.07*H;
 const z=h=>z0+h*H;
 const g={ground:[0,0,z0],pelvis:[0,ty(0.505),z(0.505)],
  spine1:[0,ty(0.575),z(0.575)],spine2:[0,ty(0.695),z(0.695)],
  neck_base:[0,ty(0.815),z(0.815)],head_base:[0,ty(0.86),z(0.86)],
  head_top:[0,ty(0.98),z1]};
 for(const s of[1,-1]){const k=s>0?"L":"R";
  g["shoulder"+k]=[s*shX,shY,shZ];g["elbow"+k]=[s*elX,elY,elZ];
  g["wrist"+k]=[s*wrX,wrY,wrZ];g["hand_tip"+k]=[s*x1*0.985,wrY*0.5,wrZ-0.02*H];
  g["hip"+k]=[s*legX*1.3,ty(0.53),z(0.528)];
  g["knee"+k]=[s*legX,ty(0.28),z(0.285)];
  g["ankle"+k]=[s*legX*0.75,ty(0.06)+0.02*H,z(0.048)];
  g["toe"+k]=[s*legX*0.8,y0+0.20*(y1-y0),z(0.012)];
  g["toe_tip"+k]=[s*legX*0.85,y0+0.06*(y1-y0),z(0.006)];}
 return g;}

let B=[],NAMES=[],IDX={},restQ=[],restP=[],relQ=[],relP=[],invRest=[],ORDER=[],CHILDREN=[];
// Ось кости в её СОБСТВЕННОЙ системе. У своего скелета это всегда Y, а у чужого
// рига оси узлов какие угодно — направление кости приходится хранить отдельно.
let BAX=[];
// ---- роли костей: своё имя и чужое приводим к общему словарю ----
const ROLES=["hips","spine1","spine2","spine3","neck","head",
 "clavicle.L","upperarm.L","forearm.L","hand.L","thigh.L","shin.L","foot.L","toe.L",
 "clavicle.R","upperarm.R","forearm.R","hand.R","thigh.R","shin.R","foot.R","toe.R"];
let ROLE={};                                   // роль -> индекс кости
const RB=r=>{const i=ROLE[r];return i===undefined?-1:i;};
const SIDEDROLES=["clavicle","upperarm","forearm","hand","thigh","shin","foot","toe"];
function detectRoles(){
 ROLE={};
 const strip=s=>s.toLowerCase().replace(/^.*[:|]/,"").replace(/[\s_.\-]/g,"");
 const sideOf=raw=>{const l=raw.toLowerCase();
  if(/left|lft|(^|[^a-z])l($|[^a-z])|\.l$|_l$/.test(l))return "L";
  if(/right|rgt|(^|[^a-z])r($|[^a-z])|\.r$|_r$/.test(l))return "R";
  return null;};
 // Несколько вариантов написания: как есть, без «left/right» и без одиночной
 // буквы стороны. Раньше буква срезалась всегда — и «Leg» превращался в «eg».
 const core=raw=>{const n0=strip(raw);
  const n1=n0.replace(/^(left|right|lft|rgt)/,"").replace(/(left|right|lft|rgt)$/,"");
  const out=[n0,n1];
  if(/^[lr][a-z]{2,}$/.test(n1))out.push(n1.slice(1));
  return out;};
 const PAT=[
  ["clavicle",/^(shoulder|clavicle|collar)$/],
  ["upperarm",/^(arm|upperarm|uparm|armupper)$/],
  ["forearm", /^(forearm|lowerarm|loarm|armlower)$/],
  ["hand",    /^hand$/],
  ["thigh",   /^(upleg|thigh|upperleg|legupper)$/],
  ["shin",    /^(leg|shin|calf|lowerleg|leglower)$/],
  ["foot",    /^(foot|ankle)$/],
  ["toe",     /^(toebase|toe|ball)$/],
  ["neck",    /^neck\d*$/],
  ["head",    /^head$/],
  ["hips",    /^(hips?|pelvis|root|cog)$/]];
 NAMES.forEach((raw,i)=>{
  const s=sideOf(raw),cs=core(raw);
  for(const[role,re]of PAT){
   if(!cs.some(c=>re.test(c)))continue;
   const key=SIDEDROLES.includes(role)?(s?role+"."+s:null):role;
   if(key&&ROLE[key]===undefined)ROLE[key]=i;
   break;}});
 // Позвоночник разбираем цепочкой по глубине: у Mixamo это Spine/Spine1/Spine2,
 // а шаблон «spine1» ловил бы и «Spine», и «Spine1» в одну роль.
 const depth=i=>{let d=0,p=B[i].parent;while(p>=0){d++;p=B[p].parent;}return d;};
 const sp=[];
 NAMES.forEach((raw,i)=>{
  if(core(raw).some(c=>/^(spine\d*|chest|upperchest|abdomen|torso)$/.test(c)))sp.push(i);});
 sp.sort((a,b)=>depth(a)-depth(b));
 ["spine1","spine2","spine3"].forEach((r,k)=>{if(sp[k]!==undefined)ROLE[r]=sp[k];});
 if(sp.length>3)ROLE.spine3=sp[sp.length-1];
 // наши собственные имена — напрямую, они точнее эвристики
 const OURS={hips:"root",spine1:"spine_01",spine2:"spine_02",spine3:"chest",
   neck:"neck",head:"head"};
 for(const k in OURS)if(IDX[OURS[k]]!==undefined)ROLE[k]=IDX[OURS[k]];
 for(const s of["L","R"]){
  const m={["clavicle."+s]:"clavicle."+s,["upperarm."+s]:"upper_arm."+s,
    ["forearm."+s]:"forearm."+s,["hand."+s]:"hand."+s,["thigh."+s]:"thigh."+s,
    ["shin."+s]:"shin."+s,["foot."+s]:"foot."+s,["toe."+s]:"toe."+s};
  for(const k in m)if(IDX[m[k]]!==undefined)ROLE[k]=IDX[m[k]];}
 return ROLE;}

// ---- скелет из скиннинга файла ----
const CFWD=[1,0,0,0, 0,0,1,0, 0,-1,0,0, 0,0,0,1];      // glTF Y-вверх -> наш Z-вверх
const CINV=[1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,0,0,1];
const mm=(a,b)=>{const o=new Array(16);
 for(let c=0;c<4;c++)for(let r=0;r<4;r++){let s=0;
  for(let k=0;k<4;k++)s+=a[k*4+r]*b[c*4+k];o[c*4+r]=s;}return o;};
const conv=m=>mm(mm(CFWD,m),CINV);
function quatFromM(m){                                  // из 3x3 по столбцам
 const t=m[0]+m[5]+m[10];let q;
 if(t>0){const s=Math.sqrt(t+1)*2;q=[s/4,(m[6]-m[9])/s,(m[8]-m[2])/s,(m[1]-m[4])/s];}
 else if(m[0]>m[5]&&m[0]>m[10]){const s=Math.sqrt(1+m[0]-m[5]-m[10])*2;
  q=[(m[6]-m[9])/s,s/4,(m[4]+m[1])/s,(m[8]+m[2])/s];}
 else if(m[5]>m[10]){const s=Math.sqrt(1+m[5]-m[0]-m[10])*2;
  q=[(m[8]-m[2])/s,(m[4]+m[1])/s,s/4,(m[9]+m[6])/s];}
 else{const s=Math.sqrt(1+m[10]-m[0]-m[5])*2;
  q=[(m[1]-m[4])/s,(m[8]+m[2])/s,(m[9]+m[6])/s,s/4];}
 return qnorm(q);}
function buildFromSkin(sk){
 const nj=sk.joints.length;
 const jIndex=new Map();sk.joints.forEach((n,i)=>jIndex.set(n,i));
 const G=sk.global.map(conv);
 const IB=sk.ibm?sk.ibm.map(conv):null;
 B=[];NAMES=[];IDX={};BAX=[];restQ=[];restP=[];invRest=[];
 for(let j=0;j<nj;j++){
  let p=sk.parentOf[sk.joints[j]],pj=-1;
  while(p>=0){if(jIndex.has(p)){pj=jIndex.get(p);break;}p=sk.parentOf[p];}
  B.push({name:sk.names[sk.joints[j]],parent:pj,deform:true,length:1});}
 NAMES=B.map(b=>b.name);NAMES.forEach((n,i)=>IDX[n]=i);
 CHILDREN=B.map(()=>[]);B.forEach((b,i)=>{if(b.parent>=0)CHILDREN[b.parent].push(i);});
 for(let j=0;j<nj;j++){
  const m=G[j];
  const s=Math.hypot(m[0],m[1],m[2])||1;                // снимаем возможный масштаб
  const r=[m[0]/s,m[1]/s,m[2]/s,0, m[4]/s,m[5]/s,m[6]/s,0, m[8]/s,m[9]/s,m[10]/s,0,0,0,0,1];
  restQ[j]=quatFromM(r);restP[j]=[m[12],m[13],m[14]];
  // Обратную матрицу привязки строим САМИ из той же жёсткой позы покоя, а не берём
  // из файла: у арматуры Mixamo масштаб 0.01, он сидит в матрицах узлов, и файловая
  // обратная матрица несёт обратный ему множитель — скиннинг разъезжается в 100 раз.
  // При своей матрице масштаб сокращается по построению, что и проверяем: в позе
  // покоя все скин-матрицы обязаны быть единичными.
  invRest[j]=m4invRigid(m4(restQ[j],restP[j]));}
 for(let j=0;j<nj;j++){
  const kids=CHILDREN[j];
  let t;
  if(kids.length)t=restP[kids[0]];
  else{const p=B[j].parent;
   const d=p>=0?[restP[j][0]-restP[p][0],restP[j][1]-restP[p][1],restP[j][2]-restP[p][2]]
               :[0,0,0.1];
   const l=Math.hypot(...d)||0.05;
   t=[restP[j][0]+d[0]/l*l*0.45,restP[j][1]+d[1]/l*l*0.45,restP[j][2]+d[2]/l*l*0.45];}
  const d=[t[0]-restP[j][0],t[1]-restP[j][1],t[2]-restP[j][2]];
  const L=Math.hypot(...d)||1e-3;
  B[j].length=L;B[j].head=restP[j].slice();B[j].tail=t.slice();
  BAX[j]=qrot(qcon(restQ[j]),[d[0]/L,d[1]/L,d[2]/L]);}
 relQ=[];relP=[];
 for(let i=0;i<nj;i++){const p=B[i].parent;
  if(p<0){relQ[i]=restQ[i];relP[i]=restP[i];}
  else{const ic=qcon(restQ[p]);relQ[i]=qmul(ic,restQ[i]);
   relP[i]=qrot(ic,[restP[i][0]-restP[p][0],restP[i][1]-restP[p][1],restP[i][2]-restP[p][2]]);}}
 ORDER=[];{const seen=new Set();
  const em=i=>{if(seen.has(i))return;if(B[i].parent>=0)em(B[i].parent);seen.add(i);ORDER.push(i);};
  for(let i=0;i<nj;i++)em(i);}
 pose=newPose();
 detectRoles();buildLimbs();
 return nj;}
function buildSkeleton(){
 B=[];NAMES=[];IDX={};
 const byName={};
 SPEC.forEach(([nm,h,t,par,conn,def],i)=>{byName[nm]=i;});
 SPEC.forEach(([nm,h,t,par,conn,def])=>{
  const H=jointPos(h),T=jointPos(t);
  const d=[T[0]-H[0],T[1]-H[1],T[2]-H[2]];
  const len=Math.hypot(...d)||1e-4;
  B.push({name:nm,parent:par===null?-1:byName[par],deform:def,
          head:H.slice(),tail:T.slice(),length:len});});
 NAMES=B.map(b=>b.name);NAMES.forEach((n,i)=>IDX[n]=i);
 CHILDREN=B.map(()=>[]);B.forEach((b,i)=>{if(b.parent>=0)CHILDREN[b.parent].push(i);});
 restQ=[];restP=[];invRest=[];relQ=[];relP=[];BAX=B.map(()=>[0,1,0]);
 for(let i=0;i<B.length;i++){
  const d=[B[i].tail[0]-B[i].head[0],B[i].tail[1]-B[i].head[1],B[i].tail[2]-B[i].head[2]];
  const L=Math.hypot(...d)||1;
  restQ[i]=qfromto([0,1,0],[d[0]/L,d[1]/L,d[2]/L]);   // ось Y кости — вдоль кости
  restP[i]=B[i].head.slice();
  invRest[i]=m4invRigid(m4(restQ[i],restP[i]));}
 for(let i=0;i<B.length;i++){const p=B[i].parent;
  if(p<0){relQ[i]=restQ[i];relP[i]=restP[i];}
  else{const ic=qcon(restQ[p]);relQ[i]=qmul(ic,restQ[i]);
   relP[i]=qrot(ic,[restP[i][0]-restP[p][0],restP[i][1]-restP[p][1],restP[i][2]-restP[p][2]]);}}
 ORDER=[];{const seen=new Set();
  const em=i=>{if(seen.has(i))return;if(B[i].parent>=0)em(B[i].parent);seen.add(i);ORDER.push(i);};
  for(let i=0;i<B.length;i++)em(i);}
 pose=newPose();
 detectRoles();buildLimbs();}

function newPose(){return{q:B.map(()=>[1,0,0,0]),loc:[0,0,0]};}
const clonePose=p=>({q:p.q.map(v=>v.slice()),loc:p.loc.slice()});
let pose=null;
const wQ=[],wP=[];
function evalPose(ps){
 for(const i of ORDER){const p=B[i].parent,lq=ps.q[i];
  const loc=(i===IDX["root"])?ps.loc:[0,0,0];
  if(p<0){const bq=relQ[i];wQ[i]=qmul(bq,lq);
   const t=qrot(bq,loc);wP[i]=[relP[i][0]+t[0],relP[i][1]+t[1],relP[i][2]+t[2]];}
  else{const bq=qmul(wQ[p],relQ[i]);wQ[i]=qmul(bq,lq);
   const a=qrot(wQ[p],relP[i]),t=qrot(bq,loc);
   wP[i]=[wP[p][0]+a[0]+t[0],wP[p][1]+a[1]+t[1],wP[p][2]+a[2]+t[2]];}}}
const head=i=>wP[i];
const tail=i=>{const a=BAX[i]||[0,1,0],L=B[i].length;
 const d=qrot(wQ[i],[a[0]*L,a[1]*L,a[2]*L]);
 return[wP[i][0]+d[0],wP[i][1]+d[1],wP[i][2]+d[2]];};
function skinMats(){const o=new Float32Array(B.length*16);
 for(let i=0;i<B.length;i++)o.set(m4mul(m4(wQ[i],wP[i]),invRest[i]),i*16);return o;}
function applyWorld(ps,i,qw){const p=B[i].parent;
 const bq=p<0?relQ[i]:qmul(wQ[p],relQ[i]);
 ps.q[i]=qnorm(qmul(qmul(qcon(bq),qmul(qw,bq)),ps.q[i]));}

// ============================================================ привязка
let MESH=null,SKIN=null,skinStale=false,RIGGED=false;
function computeWeights(power,smooth){
 const {wpos,map,count}=MESH.w;
 const deform=[];for(let i=0;i<B.length;i++)if(B[i].deform)deform.push(i);
 const K=4,ND=deform.length;
 const wi=new Uint8Array(count*K),ww=new Float32Array(count*K);
 const tmp=new Float32Array(ND);
 const p=[0,0,0];
 for(let v=0;v<count;v++){
  p[0]=wpos[v*3];p[1]=wpos[v*3+1];p[2]=wpos[v*3+2];
  let sum=0;
  for(let k=0;k<ND;k++){const b=B[deform[k]];
   const d2=segDistSq(p,b.head,b.tail);
   const w=1/(Math.pow(d2,power/2)+1e-9);
   tmp[k]=w;sum+=w;}
  // четыре сильнейших
  for(let s=0;s<K;s++){let bi=0,bv=-1;
   for(let k=0;k<ND;k++)if(tmp[k]>bv){bv=tmp[k];bi=k;}
   wi[v*K+s]=deform[bi];ww[v*K+s]=bv;tmp[bi]=-1;}
  let t=0;for(let s=0;s<K;s++)t+=ww[v*K+s];
  if(t>0)for(let s=0;s<K;s++)ww[v*K+s]/=t;}
 // Сглаживание по рёбрам сваренной сетки убирает ступеньки на суставах.
 // Плотная таблица count×костей — это 48 МБ и упор в память; держим разрежённо,
 // по K слотов на вершину, с маленьким рабочим массивом на кость.
 if(smooth>0){
  const nb=MESH.nbr,off=MESH.nbrOff,NBN=B.length;
  const scratch=new Float32Array(NBN),touched=new Int32Array(NBN);
  let ai=wi,aw=ww,bi2=new Uint8Array(count*K),bw2=new Float32Array(count*K);
  for(let it=0;it<smooth;it++){
   for(let v=0;v<count;v++){
    let nt=0;
    for(let s=0;s<K;s++){const w=aw[v*K+s];if(w<=0)continue;
     const b=ai[v*K+s];if(scratch[b]===0)touched[nt++]=b;scratch[b]+=w*0.35;}
    const a=off[v],e2=off[v+1],cnt=e2-a;
    if(cnt){const f=0.65/cnt;
     for(let e=a;e<e2;e++){const u=nb[e];
      for(let s=0;s<K;s++){const w=aw[u*K+s];if(w<=0)continue;
       const b=ai[u*K+s];if(scratch[b]===0)touched[nt++]=b;scratch[b]+=w*f;}}}
    let t=0;
    for(let s=0;s<K;s++){let best=-1,bv=-1;
     for(let k=0;k<nt;k++){const b=touched[k],q=scratch[b];if(q>bv){bv=q;best=b;}}
     if(best<0||bv<=0){bi2[v*K+s]=0;bw2[v*K+s]=0;continue;}
     bi2[v*K+s]=best;bw2[v*K+s]=bv;t+=bv;scratch[best]=-1;}
    for(let k=0;k<nt;k++)scratch[touched[k]]=0;
    if(t>0)for(let s=0;s<K;s++)bw2[v*K+s]/=t;}
   const ti=ai;ai=bi2;bi2=ti;const tw=aw;aw=bw2;bw2=tw;}
  wi.set(ai);ww.set(aw);}
 // разворачиваем на исходные вершины
 const N=MESH.pos.length/3;
 const SI=new Uint8Array(N*4),SW=new Uint8Array(N*4);
 for(let i=0;i<N;i++){const v=map[i];
  for(let s=0;s<4;s++){SI[i*4+s]=wi[v*4+s];
   SW[i*4+s]=Math.max(0,Math.min(255,Math.round(ww[v*4+s]*255)));}}
 SKIN={idx:SI,wt:SW,perBone:(()=>{const c={};
  for(let v=0;v<count;v++)c[NAMES[wi[v*4]]]=(c[NAMES[wi[v*4]]]||0)+1;return c;})(),
  welded:count};
 skinStale=false;
 uploadSkin();}

// соседи по рёбрам сваренной сетки (CSR)
function buildNeighbours(){
 const {map,count}=MESH.w,idx=MESH.idx;
 const cnt=new Uint32Array(count+1);
 const add=[];
 const seen=new Set();
 for(let t=0;t<idx.length;t+=3){
  const a=map[idx[t]],b=map[idx[t+1]],c=map[idx[t+2]];
  for(const[u,v]of[[a,b],[b,c],[c,a]]){
   if(u===v)continue;
   const k=u<v?u*count+v:v*count+u;
   if(seen.has(k))continue;seen.add(k);
   add.push(u,v);cnt[u+1]++;cnt[v+1]++;}}
 for(let i=0;i<count;i++)cnt[i+1]+=cnt[i];
 const off=cnt.slice(),fill=cnt.slice(0,count),nb=new Uint32Array(off[count]);
 for(let i=0;i<add.length;i+=2){const u=add[i],v=add[i+1];
  nb[fill[u]++]=v;nb[fill[v]++]=u;}
 MESH.nbr=nb;MESH.nbrOff=off;}
</script>
<script>
// ============================================================ WebGL
const cv=document.getElementById("gl"),ov=document.getElementById("ov"),oc=ov.getContext("2d");
const bg=document.getElementById("bg"),bc=bg.getContext("2d");
const GLOPT={antialias:true,alpha:true,premultipliedAlpha:false,preserveDrawingBuffer:true};
const gl=cv.getContext("webgl2",GLOPT)||cv.getContext("webgl",GLOPT)
      ||cv.getContext("experimental-webgl",GLOPT);
if(!gl)showFail("браузер не даёт WebGL. Обычно это выключенное аппаратное ускорение: "+
  "Chrome → Настройки → Система → «Использовать аппаратное ускорение», затем перезапуск. "+
  "Проверить можно на chrome://gpu");
const isGL2=!!(gl&&gl.TEXTURE_BINDING_3D);
if(!isGL2)gl.getExtension("OES_element_index_uint");
let MAXB=32;
const VSRC=nb=>`attribute vec3 aP;attribute vec3 aN;attribute vec2 aT;attribute vec4 aI;attribute vec4 aW;
uniform mat4 uMVP;uniform mat4 uB[`+nb+`];uniform float uSkin;
varying vec3 vN;varying vec3 vP;varying vec2 vT;varying vec4 vWI;varying vec4 vWW;
void main(){mat4 s=uB[int(aI.x)]*aW.x+uB[int(aI.y)]*aW.y+uB[int(aI.z)]*aW.z+uB[int(aI.w)]*aW.w;
 mat4 m=uSkin>0.5?s:mat4(1.0);
 vec4 p=m*vec4(aP,1.0);vN=mat3(m)*aN;vP=p.xyz;vT=aT;vWI=aI;vWW=aW;
 gl_Position=uMVP*p;}`;
const FS=`precision mediump float;varying vec3 vN;varying vec3 vP;varying vec2 vT;
varying vec4 vWI;varying vec4 vWW;
uniform vec3 uCam;uniform float uMode;uniform float uHi;uniform sampler2D uTex;uniform float uHasTex;
uniform vec3 uLDir;uniform vec4 uLP;uniform float uFollow;   // uLP = засветка, яркость, контур, блик
vec3 heat(float t){t=clamp(t,0.0,1.0);
 return t<0.5?mix(vec3(0.10,0.16,0.42),vec3(0.25,0.75,0.55),t*2.0)
             :mix(vec3(0.25,0.75,0.55),vec3(0.98,0.85,0.30),(t-0.5)*2.0);}
void main(){vec3 n=normalize(vN);vec3 v=normalize(uCam-vP);
 vec3 l=uFollow>0.5?normalize(v+uLDir):normalize(uLDir);
 float d=max(dot(n,l),0.0)*uLP.y+uLP.x;
 vec3 base=vec3(0.82,0.83,0.86);
 if(uMode>1.5){float w=0.0;
  if(abs(vWI.x-uHi)<0.5)w=vWW.x; else if(abs(vWI.y-uHi)<0.5)w=vWW.y;
  else if(abs(vWI.z-uHi)<0.5)w=vWW.z; else if(abs(vWI.w-uHi)<0.5)w=vWW.w;
  base=heat(w);}
 else if(uMode>0.5&&uHasTex>0.5)base=texture2D(uTex,vT).rgb;
 float rim=pow(1.0-max(dot(n,v),0.0),2.5)*uLP.z;
 float spec=pow(max(dot(reflect(-l,n),v),0.0),28.0)*uLP.w;
 gl_FragColor=vec4(base*d+rim+spec,1.0);}`;
function sh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);
 if(!gl.getShaderParameter(o,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(o));return o;}
let prog=null;
const U={};
const BUFS={};
// Массив костей в шейдере надо объявлять под ФАКТИЧЕСКОЕ их число. При жёстких 32
// у рига Mixamo на 57 костей ноги стоят с индекса 47 — треть привязок уходила за
// границу массива, и меш ног переставал слушаться скелета.
function buildProgram(nb){
 const cap=Math.max(1,Math.floor((gl.getParameter(gl.MAX_VERTEX_UNIFORM_VECTORS)-32)/4));
 nb=Math.max(32,Math.min(nb,cap));
 if(prog&&nb<=MAXB)return MAXB;
 if(prog)gl.deleteProgram(prog);
 prog=gl.createProgram();
 gl.attachShader(prog,sh(gl.VERTEX_SHADER,VSRC(nb)));
 gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,FS));
 gl.linkProgram(prog);
 if(!gl.getProgramParameter(prog,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(prog));
 gl.useProgram(prog);gl.enable(gl.DEPTH_TEST);
 for(const k of["uMVP","uB","uCam","uMode","uHi","uTex","uHasTex","uSkin",
                "uLDir","uLP","uFollow"])
  U[k]=gl.getUniformLocation(prog,k);
 MAXB=nb;
 for(const k in BUFS)bindAttr(BUFS[k]);      // локации атрибутов сменились
 return nb;}
function bindAttr(e){
 const l=gl.getAttribLocation(prog,e.attr);
 if(l<0)return;
 gl.bindBuffer(gl.ARRAY_BUFFER,e.buf);
 gl.enableVertexAttribArray(l);
 gl.vertexAttribPointer(l,e.n,e.type,e.norm,0,0);}
function ab(name,data,n,type,norm,attr){
 const e=BUFS[name]||(BUFS[name]={buf:gl.createBuffer()});
 e.n=n;e.type=type;e.norm=norm;e.attr=attr;
 gl.bindBuffer(gl.ARRAY_BUFFER,e.buf);
 gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);
 bindAttr(e);}
buildProgram(32);
let EB=null,NIDX=0,TEX=null;
function uploadMesh(){
 ab("p",MESH.pos,3,gl.FLOAT,false,"aP");
 ab("n",MESH.nor,3,gl.FLOAT,false,"aN");
 ab("t",MESH.uv,2,gl.FLOAT,false,"aT");
 if(!EB)EB=gl.createBuffer();
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,EB);
 gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,MESH.idx,gl.STATIC_DRAW);
 NIDX=MESH.idx.length;
 const n=MESH.pos.length/3;
 ab("si",new Uint8Array(n*4),4,gl.UNSIGNED_BYTE,false,"aI");
 ab("sw",new Uint8Array(n*4),4,gl.UNSIGNED_BYTE,true,"aW");}
function uploadSkin(){
 ab("si",SKIN.idx,4,gl.UNSIGNED_BYTE,false,"aI");
 ab("sw",SKIN.wt,4,gl.UNSIGNED_BYTE,true,"aW");}
function setLight(){
 const L=OPT.light;
 const a=L.az*Math.PI/180,e=L.el*Math.PI/180;
 const d=L.follow?[0.22,0,0.85]
   :[Math.cos(e)*Math.sin(a),-Math.cos(e)*Math.cos(a),Math.sin(e)];
 gl.uniform3fv(U.uLDir,new Float32Array(d));
 gl.uniform4fv(U.uLP,new Float32Array([L.amb,L.gain,L.rim,L.spec]));
 gl.uniform1f(U.uFollow,L.follow?1:0);}
function setTexture(src){
 const im=new Image();
 im.onload=()=>{TEX=TEX||gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D,TEX);
  // В glTF начало UV — ЛЕВЫЙ ВЕРХ, V растёт вниз, так что картинку переворачивать
  // НЕЛЬЗЯ. С flip=true развёртка садится зеркально по вертикали: подошва получает
  // цвет яркостью 64 вместо 12, платье перестаёт быть зелёным.
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,im);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  document.getElementById("cTex").checked=true;draw();};
 im.src=typeof src==="string"?src:URL.createObjectURL(src);}
</script>
<script>
// ============================================================ вид и сцена
let STEP=0,selBone=-1,selJoint=null,axisLock=null,drag=null,orbit=null;
// Настройки панелей живут ЗДЕСЬ, а не в DOM: panel() перерисовывает разметку на
// каждый клик, и любое состояние, записанное только в атрибут, тут же терялось.
const OPT={sym:false,hold:false,chain:1,ik:true,wPow:4,wSmooth:6,
           cell:160,scale:0,allFrames:false,tool:"move",pinFeet:true,
           limits:true,footLock:true,fitIters:600,fitFrame:1,
           light:{follow:true,az:35,el:45,amb:0.32,gain:0.70,rim:0.14,spec:0.0}};
const C={az:0.35,el:0.12,dist:3.2,tx:0,ty:0,tz:0};
let Z_FEET=0,HGT=1;
const RS={block:"",dir:"SE",op:0.5,zoom:3,iso:false,grid:false,dy:0,
          gear:true,gearOp:0.85,sw:1,sh:1};
const ANCHOR_FRAC=0.80;
const refImg={};
function refStrip(d,kind){
 if(!RS.block)return null;
 const set=(kind==="gear")?(REF.blocks[RS.block].gear||null):REF.blocks[RS.block].strips;
 if(!set||!set[d])return null;
 const k=RS.block+"/"+(kind||"body")+"/"+d;
 if(!refImg[k]){const im=new Image();im.onload=draw;im.src=set[d];refImg[k]=im;}
 return refImg[k].complete?refImg[k]:null;}
const hasGear=()=>!!(RS.block&&REF.blocks[RS.block]&&REF.blocks[RS.block].gear);
const isoOn=()=>RS.iso&&MESH;
function camPos(dir){
 if(isoOn()){const t=REF.tilt*Math.PI/180,a=(REF.az[dir||RS.dir]||0)*Math.PI/180,D=20;
  return[D*Math.cos(t)*Math.sin(a),-D*Math.cos(t)*Math.cos(a),Z_FEET+D*Math.sin(t)];}
 const ce=Math.cos(C.el);
 return[C.tx+C.dist*ce*Math.sin(C.az),C.ty-C.dist*ce*Math.cos(C.az),C.tz+C.dist*Math.sin(C.el)];}
const camTgt=()=>isoOn()?[0,0,Z_FEET]:[C.tx,C.ty,C.tz];
function views(){
 if(!(RS.grid&&RS.block))return[{dir:RS.dir,rect:{x:0,y:0,w:cv.width,h:cv.height}}];
 const cw=cv.width/4,ch=cv.height/2;
 return REF.dirs.map((d,i)=>({dir:d,rect:{x:(i%4)*cw,y:Math.floor(i/4)*ch,w:cw,h:ch}}));}
// Габариты подгоняются МАСШТАБОМ МИРА, а не в шейдере: тогда меш, точки суставов
// и обратная проекция при перетаскивании масштабируются одной матрицей и не
// расходятся. Ширина берётся вокруг осевой линии, высота — вокруг точки ног,
// поэтому персонаж не всплывает над землёй и не уходит вбок.
function sclMat(){const s=RS.sw,h=RS.sh;
 return new Float32Array([s,0,0,0, 0,s,0,0, 0,0,h,0, 0,0,Z_FEET*(1-h),1]);}
const withScl=M=>(RS.sw===1&&RS.sh===1)?M:m4mul(M,sclMat());
// Смещение по высоте задано в ЭКРАННЫХ пикселях при текущем увеличении. Чтобы
// подгонка позы и выгрузка спрайтов целились ровно туда, что видно на экране,
// переводим его в единицы мира и пересчитываем под масштаб конкретного вида.
const dyWorld=()=>RS.dy/((REF.px_per_unit*RS.zoom)||1);
const oyFor=(pxu,vpH)=>(1-2*ANCHOR_FRAC)+2*dyWorld()*pxu/vpH;   // плюс — вверх
function vpFor(v){
 const d=window.devicePixelRatio||1;
 if(!isoOn())return withScl(m4mul(persp(0.72,v.rect.w/v.rect.h,0.05,60),
                                  lookAt(camPos(),camTgt(),[0,0,1])));
 const pxu=REF.px_per_unit*RS.zoom*d;
 return withScl(m4mul(ortho(v.rect.w/pxu,v.rect.h/pxu,0.1,80,0,oyFor(pxu,v.rect.h)),
                      lookAt(camPos(v.dir),[0,0,Z_FEET],[0,0,1])));}
const anchorOf=r=>[r.x+r.w/2,r.y+r.h*ANCHOR_FRAC];
function blitRef(g,alpha,v,kind){
 const im=refStrip(v.dir,kind);if(!im)return false;
 const w=REF.window,d=window.devicePixelRatio||1,zz=RS.zoom*d,[ax,ay]=anchorOf(v.rect);
 const n=REF.blocks[RS.block].frames;
 // Кадр берём из того же поля, что и подгонка позы (fitPrepare), иначе на экране
 // один кадр эталона, а оптимизатор целится в другой.
 const fi=Math.min(n-1,Math.max(0,((OPT.fitFrame|0)||1)-1));
 g.imageSmoothingEnabled=false;g.globalAlpha=alpha;
 g.drawImage(im,fi*w.w,0,w.w,w.h, ax-w.ax*zz, ay-w.ay*zz, w.w*zz, w.h*zz);
 g.globalAlpha=1;return true;}
let VIEWS=[],ACT=null;
function projIn(p,M,r){const v=[p[0],p[1],p[2],1],o=[0,0,0,0];
 for(let q=0;q<4;q++){let s=0;for(let k=0;k<4;k++)s+=M[k*4+q]*v[k];o[q]=s;}
 if(o[3]<=0)return null;
 return[r.x+(o[0]/o[3]*0.5+0.5)*r.w,r.y+(0.5-o[1]/o[3]*0.5)*r.h,o[3]];}
function viewAt(mx,my){for(const v of VIEWS){const r=v.rect;
 if(mx>=r.x&&mx<r.x+r.w&&my>=r.y&&my<r.y+r.h)return v;}return ACT;}
function resize(){const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;
 for(const c of[cv,ov,bg]){c.width=Math.max(1,Math.round(r.width*d));
  c.height=Math.max(1,Math.round(r.height*d));
  c.style.width=r.width+"px";c.style.height=r.height+"px";}}

const AXES=[{n:"X",v:[1,0,0],c:"#ff5f5f",t:"вбок"},{n:"Y",v:[0,1,0],c:"#5fd46a",t:"вперёд/назад"},
            {n:"Z",v:[0,0,1],c:"#5fa8ff",t:"вверх/вниз"}];
// ---- гизмо вращения: три кольца по мировым осям вокруг НАЧАЛА кости ----
function planeBasis(A){
 let b1=Math.abs(A[0])<0.9?[1,0,0]:[0,1,0];
 b1=[A[1]*b1[2]-A[2]*b1[1],A[2]*b1[0]-A[0]*b1[2],A[0]*b1[1]-A[1]*b1[0]];
 const l=Math.hypot(...b1)||1;b1=b1.map(v=>v/l);
 const b2=[A[1]*b1[2]-A[2]*b1[1],A[2]*b1[0]-A[0]*b1[2],A[0]*b1[1]-A[1]*b1[0]];
 return[b1,b2];}
function rotGizmo(P){
 if(!ACT||!P)return null;
 const pj=projIn(P,ACT.vp,ACT.rect);if(!pj)return null;
 const d=window.devicePixelRatio||1,RAD=62*d,PR=0.09*HGT;
 // Масштаб «пикселей на единицу» берём по НАИМЕНЕЕ сплющенной оси: пробник вдоль
 // одной оси в косом ракурсе занижает его втрое, и кольца выходят крошечными.
 let scale=0;
 for(const a of AXES){
  const p1=projIn([P[0]+a.v[0]*PR,P[1]+a.v[1]*PR,P[2]+a.v[2]*PR],ACT.vp,ACT.rect);
  if(p1)scale=Math.max(scale,Math.hypot(p1[0]-pj[0],p1[1]-pj[1])/PR);}
 const R=scale>1e-6?RAD/scale:PR;
 const view=camPos(ACT.dir);
 let vd=[view[0]-P[0],view[1]-P[1],view[2]-P[2]];
 const vl=Math.hypot(...vd)||1;vd=vd.map(v=>v/vl);
 const rings=AXES.map(a=>{
  const[b1,b2]=planeBasis(a.v);
  const pts=[];
  for(let k=0;k<=56;k++){const t=k/56*Math.PI*2,c=Math.cos(t),s=Math.sin(t);
   const w=[P[0]+R*(b1[0]*c+b2[0]*s),P[1]+R*(b1[1]*c+b2[1]*s),P[2]+R*(b1[2]*c+b2[2]*s)];
   const q=projIn(w,ACT.vp,ACT.rect);if(q)pts.push(q);}
  const edge=Math.abs(a.v[0]*vd[0]+a.v[1]*vd[1]+a.v[2]*vd[2])<0.20;  // кольцо с ребра
  return{a,b1,b2,pts,edge};});
 return{P,pj,R,rings};}
function drawRotGizmo(P){
 const g=rotGizmo(P);if(!g)return;
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
function hitRot(mx,my,P){
 const g=rotGizmo(P);if(!g)return null;
 const d=window.devicePixelRatio||1;let best=null,bd=12*d;
 for(const r of g.rings){if(r.edge)continue;
  for(let i=1;i<r.pts.length;i++){
   const dd=segDist2D(mx,my,r.pts[i-1][0],r.pts[i-1][1],r.pts[i][0],r.pts[i][1]);
   if(dd<bd){bd=dd;best=r;}}}
 return best;}
function ringAngle(v,mx,my,P,r){
 const{n,u}=mouseRay(v,mx,my),A=r.a.v;
 const den=u[0]*A[0]+u[1]*A[1]+u[2]*A[2];
 if(Math.abs(den)>0.06){
  const t=((P[0]-n[0])*A[0]+(P[1]-n[1])*A[1]+(P[2]-n[2])*A[2])/den;
  const p=[n[0]+u[0]*t-P[0],n[1]+u[1]*t-P[1],n[2]+u[2]*t-P[2]];
  return Math.atan2(p[0]*r.b2[0]+p[1]*r.b2[1]+p[2]*r.b2[2],
                    p[0]*r.b1[0]+p[1]*r.b1[1]+p[2]*r.b1[2]);}
 const pj=projIn(P,v.vp,v.rect);                     // ось почти в плоскости экрана
 return pj?Math.atan2(my-pj[1],mx-pj[0]):null;}
function gizmoAt(P){
 if(!ACT||!P)return null;
 const pj=projIn(P,ACT.vp,ACT.rect);if(!pj)return null;
 const d=window.devicePixelRatio||1,LEN=58*d,PR=0.08*HGT;
 const arms=AXES.map(a=>{
  const p=projIn([P[0]+a.v[0]*PR,P[1]+a.v[1]*PR,P[2]+a.v[2]*PR],ACT.vp,ACT.rect);
  if(!p)return null;
  const L=Math.hypot(p[0]-pj[0],p[1]-pj[1]);
  if(L<1e-3)return{a,tip:pj,flat:true,raw:L,off:[0,0]};
  const k=PR*LEN/L;
  const tip=projIn([P[0]+a.v[0]*k,P[1]+a.v[1]*k,P[2]+a.v[2]*k],ACT.vp,ACT.rect);
  return tip?{a,tip,flat:false,raw:L,off:[0,0]}:null;});
 // ось почти вдоль взгляда: её экранная длина до нормировки много меньше прочих
 const mx=Math.max(...arms.map(a=>a?a.raw:0));
 for(const a of arms)if(a&&a.raw<0.12*mx)a.flat=true;
 const dir=arms.map(a=>{if(!a)return null;
  const dx=a.tip[0]-pj[0],dy=a.tip[1]-pj[1],L=Math.hypot(dx,dy)||1;return[dx/L,dy/L];});
 for(let i=0;i<3;i++)for(let j=i+1;j<3;j++){
  if(!dir[i]||!dir[j])continue;
  if(Math.abs(dir[i][0]*dir[j][1]-dir[i][1]*dir[j][0])>0.20)continue;
  const p=[-dir[i][1],dir[i][0]],k=9*(window.devicePixelRatio||1);
  arms[i].off=[p[0]*k,p[1]*k];arms[j].off=[-p[0]*k,-p[1]*k];}
 return{P,pj,arms};}
const armSeg=(g,a)=>[g.pj[0]+a.off[0],g.pj[1]+a.off[1],a.tip[0]+a.off[0],a.tip[1]+a.off[1]];
function segDist2D(px,py,x1,y1,x2,y2){const dx=x2-x1,dy=y2-y1,L=dx*dx+dy*dy;
 let t=L?((px-x1)*dx+(py-y1)*dy)/L:0;t=t<0?0:t>1?1:t;
 return Math.hypot(px-(x1+dx*t),py-(y1+dy*t));}
function drawGizmo(P){
 const g=gizmoAt(P);if(!g)return;
 const d=window.devicePixelRatio||1;
 for(const a of g.arms){if(!a)continue;
  const on=(drag&&drag.axis&&drag.axis.n===a.a.n)||axisLock===a.a.n;
  const s=armSeg(g,a);
  oc.strokeStyle=a.a.c;oc.lineWidth=(on?4.5:2.5)*d;
  oc.beginPath();oc.moveTo(s[0],s[1]);oc.lineTo(s[2],s[3]);oc.stroke();
  oc.fillStyle=a.a.c;oc.beginPath();oc.arc(s[2],s[3],(on?6.5:5)*d,0,7);oc.fill();
  oc.font="600 "+(11*d)+"px Segoe UI";oc.fillText(a.a.n,s[2]+8*d,s[3]-7*d);}}
function hitAxis(mx,my,P){
 const g=gizmoAt(P);if(!g)return null;
 const d=window.devicePixelRatio||1;let best=null,bd=11*d;
 for(const a of g.arms){if(!a)continue;const s=armSeg(g,a);
  const dd=segDist2D(mx,my,s[0],s[1],s[2],s[3]);if(dd<bd){bd=dd;best=a.a;}}
 return best;}
function mouseRay(v,mx,my){
 const inv=invMat(v.vp);
 const ndc=[(mx-v.rect.x)/v.rect.w*2-1,1-(my-v.rect.y)/v.rect.h*2];
 const na=mulv(inv,[ndc[0],ndc[1],-1,1]),fa=mulv(inv,[ndc[0],ndc[1],1,1]);
 const n=[na[0]/na[3],na[1]/na[3],na[2]/na[3]];
 const f=[fa[0]/fa[3],fa[1]/fa[3],fa[2]/fa[3]];
 let u=[f[0]-n[0],f[1]-n[1],f[2]-n[2]];const L=Math.hypot(...u)||1;
 return{n,u:u.map(c=>c/L)};}
function rayPoint(v,mx,my,Jp){const{n,u}=mouseRay(v,mx,my);
 const t=(Jp[0]-n[0])*u[0]+(Jp[1]-n[1])*u[1]+(Jp[2]-n[2])*u[2];
 return[n[0]+u[0]*t,n[1]+u[1]*t,n[2]+u[2]*t];}
function axisParam(v,mx,my,Jp,A){const{n,u}=mouseRay(v,mx,my);
 const w=[Jp[0]-n[0],Jp[1]-n[1],Jp[2]-n[2]];
 const b=A[0]*u[0]+A[1]*u[1]+A[2]*u[2];
 const d=A[0]*w[0]+A[1]*w[1]+A[2]*w[2];
 const e=u[0]*w[0]+u[1]*w[1]+u[2]*w[2];
 const den=1-b*b;if(Math.abs(den)<1e-5)return null;
 return(b*e-d)/den;}
// ============================================================ двухкостный IK
// CCD крутит цепь итерациями и выбирает произвольное решение из бесконечного
// множества — локоть уезжает куда попало. Для руки и ноги решение считается
// формулой: положение локтя задаётся пересечением двух сфер, а из окружности
// решений выбирается точка по ПОЛЮСУ. Так локоть не «щёлкает» и не выворачивается.
let LIMB={},POLEOF={},FITB=[];
function buildLimbs(){
 LIMB={};POLEOF={};
 for(const s of["L","R"]){
  const ua=RB("upperarm."+s),fa=RB("forearm."+s);
  if(ua>=0&&fa>=0){LIMB[NAMES[fa]]=[NAMES[ua],NAMES[fa],"arm",s];
   POLEOF[NAMES[ua]]=NAMES[fa];}
  const th=RB("thigh."+s),sh=RB("shin."+s);
  if(th>=0&&sh>=0){LIMB[NAMES[sh]]=[NAMES[th],NAMES[sh],"leg",s];
   POLEOF[NAMES[th]]=NAMES[sh];}}
 // какие кости шевелит автоподбор и насколько охотно
 const W={ "upperarm.L":1,"forearm.L":1,"hand.L":.5,"upperarm.R":1,"forearm.R":1,
   "hand.R":.5,"thigh.L":1,"shin.L":1,"foot.L":.6,"thigh.R":1,"shin.R":1,"foot.R":.6,
   "spine1":.7,"spine2":.7,"spine3":.7,"neck":.5,"head":.5,
   "clavicle.L":.4,"clavicle.R":.4};
 FITB=[];
 for(const r in W){const i=RB(r);if(i>=0)FITB.push([NAMES[i],W[r]]);}}
const POLE={"arm.L":0,"arm.R":0,"leg.L":0,"leg.R":0};     // доворот полюса, градусы
const poleKey=k=>{const L=LIMB[k];return L[2]+"."+L[3];};
function poleDir(kind,axis){
 // локоть смотрит назад-вниз, колено — вперёд; персонаж обращён в −Y
 let base=kind==="arm"?[0,1,-0.35]:[0,-1,-0.2];
 const l=Math.hypot(...base);base=base.map(c=>c/l);
 return base;}
function rotAbout(v,axis,ang){
 const c=Math.cos(ang),s=Math.sin(ang);
 const d=axis[0]*v[0]+axis[1]*v[1]+axis[2]*v[2];
 const cr=[axis[1]*v[2]-axis[2]*v[1],axis[2]*v[0]-axis[0]*v[2],axis[0]*v[1]-axis[1]*v[0]];
 return[v[0]*c+cr[0]*s+axis[0]*d*(1-c),v[1]*c+cr[1]*s+axis[1]*d*(1-c),
        v[2]*c+cr[2]*s+axis[2]*d*(1-c)];}
// reset=true — сначала вернуть кость в позу покоя. Без этого доворот идёт ОТ
// текущего положения, скрутка вокруг оси кости накапливается за перетаскивание
// (замерено: 36° за три круга запястьем), и рука выворачивается.
function pointBone(i,to,reset){
 if(reset)pose.q[i]=[1,0,0,0];
 evalPose(pose);
 const h0=head(i),t=tail(i);
 let a=[t[0]-h0[0],t[1]-h0[1],t[2]-h0[2]];
 let b=[to[0]-h0[0],to[1]-h0[1],to[2]-h0[2]];
 const la=Math.hypot(...a),lb=Math.hypot(...b);
 if(la<1e-6||lb<1e-6)return;
 applyWorld(pose,i,qfromto(a.map(c=>c/la),b.map(c=>c/lb)));
 evalPose(pose);}
function ik2(key,target){
 const[an,bn,kind,side]=LIMB[key];
 const ia=IDX[an],ib=IDX[bn];
 evalPose(pose);
 const A=head(ia).slice(),L1=B[ia].length,L2=B[ib].length;
 let v=[target[0]-A[0],target[1]-A[1],target[2]-A[2]];
 let d=Math.hypot(...v);
 if(d<1e-6){v=[0,0,-1];d=1;}
 const n=v.map(c=>c/d);
 const dc=Math.max(Math.abs(L1-L2)+1e-4,Math.min(L1+L2-1e-4,d));
 const T=[A[0]+n[0]*dc,A[1]+n[1]*dc,A[2]+n[2]*dc];
 const a=(L1*L1-L2*L2+dc*dc)/(2*dc);
 const h=Math.sqrt(Math.max(0,L1*L1-a*a));
 let u=rotAbout(poleDir(kind),n,POLE[kind+"."+side]*Math.PI/180);
 const dp=u[0]*n[0]+u[1]*n[1]+u[2]*n[2];
 u=[u[0]-n[0]*dp,u[1]-n[1]*dp,u[2]-n[2]*dp];
 let ul=Math.hypot(...u);
 if(ul<1e-5){const t=Math.abs(n[0])<0.9?[1,0,0]:[0,1,0];
  u=[n[1]*t[2]-n[2]*t[1],n[2]*t[0]-n[0]*t[2],n[0]*t[1]-n[1]*t[0]];ul=Math.hypot(...u);}
 u=u.map(c=>c/ul);
 const E=[A[0]+n[0]*a+u[0]*h,A[1]+n[1]*a+u[1]*h,A[2]+n[2]*a+u[2]*h];
 pointBone(ia,E,true);
 pointBone(ib,T,true);}
// Какой угол полюса отвечает ТЕКУЩЕМУ положению локтя. Нужен при захвате: поза
// могла прийти из библиотеки или из FK, и первый же вызов ik2 иначе дёрнет локоть
// в аналитическое решение при старом угле.
function poleFromPose(key){
 const[an,bn,kind,side]=LIMB[key];
 evalPose(pose);
 const A=head(IDX[an]),E=tail(IDX[an]),T=tail(IDX[bn]);
 let n=[T[0]-A[0],T[1]-A[1],T[2]-A[2]];
 const l=Math.hypot(...n);if(l<1e-6)return null;
 n=n.map(c=>c/l);
 let v=[E[0]-A[0],E[1]-A[1],E[2]-A[2]];
 const dp=v[0]*n[0]+v[1]*n[1]+v[2]*n[2];
 v=[v[0]-n[0]*dp,v[1]-n[1]*dp,v[2]-n[2]*dp];
 const vl=Math.hypot(...v);if(vl<1e-6)return null;
 v=v.map(c=>c/vl);
 let b1=poleDir(kind);
 const d2=b1[0]*n[0]+b1[1]*n[1]+b1[2]*n[2];
 b1=[b1[0]-n[0]*d2,b1[1]-n[1]*d2,b1[2]-n[2]*d2];
 const bl=Math.hypot(...b1)||1;b1=b1.map(c=>c/bl);
 const b2=[n[1]*b1[2]-n[2]*b1[1],n[2]*b1[0]-n[0]*b1[2],n[0]*b1[1]-n[1]*b1[0]];
 return Math.atan2(v[0]*b2[0]+v[1]*b2[1]+v[2]*b2[2],
                   v[0]*b1[0]+v[1]*b1[1]+v[2]*b1[2])*180/Math.PI;}
// доворот полюса мышью: угол вокруг оси плечо→кисть
function poleAngleFromMouse(key,v,mx,my){
 const[an,bn,kind,side]=LIMB[key];
 evalPose(pose);
 const A=head(IDX[an]),T=tail(IDX[bn]);
 let n=[T[0]-A[0],T[1]-A[1],T[2]-A[2]];
 const l=Math.hypot(...n)||1;n=n.map(c=>c/l);
 const M=[(A[0]+T[0])/2,(A[1]+T[1])/2,(A[2]+T[2])/2];
 const{n:ro,u:ru}=mouseRay(v,mx,my);
 const den=ru[0]*n[0]+ru[1]*n[1]+ru[2]*n[2];
 if(Math.abs(den)<0.05)return null;
 const t=((M[0]-ro[0])*n[0]+(M[1]-ro[1])*n[1]+(M[2]-ro[2])*n[2])/den;
 const p=[ro[0]+ru[0]*t-M[0],ro[1]+ru[1]*t-M[1],ro[2]+ru[2]*t-M[2]];
 let b1=poleDir(kind);
 const dp=b1[0]*n[0]+b1[1]*n[1]+b1[2]*n[2];
 b1=[b1[0]-n[0]*dp,b1[1]-n[1]*dp,b1[2]-n[2]*dp];
 const bl=Math.hypot(...b1)||1;b1=b1.map(c=>c/bl);
 const b2=[n[1]*b1[2]-n[2]*b1[1],n[2]*b1[0]-n[0]*b1[2],n[0]*b1[1]-n[1]*b1[0]];
 return Math.atan2(p[0]*b2[0]+p[1]*b2[1]+p[2]*b2[2],
                   p[0]*b1[0]+p[1]*b1[1]+p[2]*b1[2])*180/Math.PI;}
// стопы прибиты: двигаем корпус, ноги дорешиваются к прежним щиколоткам
function ankles(){evalPose(pose);const o={};
 for(const s of["L","R"]){const i=RB("shin."+s);if(i>=0)o[s]=tail(i).slice();}
 return o;}
function replantFeet(a){for(const s of["L","R"]){
 const i=RB("shin."+s);
 if(i<0||!a[s]||!LIMB[NAMES[i]])continue;
 // Полюс колена обязательно снять с ТЕКУЩЕЙ позы. Иначе каждый пересчёт слегка
 // доворачивает бедро к старому полюсу, а пересчёт идёт на каждое движение мыши —
 // за сотню кадров набегает треть единицы, и ноги уползают сами собой.
 const cur=poleFromPose(NAMES[i]);
 if(cur!==null)POLE[poleKey(NAMES[i])]=cur;
 ik2(NAMES[i],a[s]);}}
// влияет ли эта кость на ноги вообще: рука на них подействовать не может
function affectsLegs(i){
 for(const s of["L","R"]){let j=RB("thigh."+s);
  while(j>=0){if(j===i)return true;j=B[j].parent;}}
 return false;}

// ============================================================ пределы суставов
// Без них плечо, бедро и шея крутятся на любой угол, и поза уходит туда, куда
// живой человек не встанет. Конус — отклонение от позы покоя, второе число —
// предел скрутки вокруг оси кости. Градусы.
const LIMR={spine1:[35,25],spine2:[35,25],spine3:[30,25],neck:[45,35],head:[45,35],
 "clavicle.L":[25,20],"clavicle.R":[25,20],"upperarm.L":[110,80],"upperarm.R":[110,80],
 "forearm.L":[150,90],"forearm.R":[150,90],"hand.L":[70,60],"hand.R":[70,60],
 "thigh.L":[100,45],"thigh.R":[100,45],"shin.L":[150,25],"shin.R":[150,25],
 "foot.L":[55,35],"foot.R":[55,35],"toe.L":[45,20],"toe.R":[45,20]};
const LIMIT={"spine_01":[35,25],"spine_02":[35,25],"chest":[30,25],"neck":[45,35],
 "head":[45,35],"clavicle.L":[25,20],"clavicle.R":[25,20],
 "upper_arm.L":[110,80],"upper_arm.R":[110,80],"forearm.L":[150,90],"forearm.R":[150,90],
 "hand.L":[70,60],"hand.R":[70,60],"hip.L":[20,20],"hip.R":[20,20],
 "thigh.L":[100,45],"thigh.R":[100,45],"shin.L":[150,25],"shin.R":[150,25],
 "foot.L":[55,35],"foot.R":[55,35],"toe.L":[45,20],"toe.R":[45,20]};
function limitOf(i){
 for(const r in ROLE)if(ROLE[r]===i&&LIMR[r])return LIMR[r];
 return LIMIT[NAMES[i]]||null;}
function clampLocal(i){
 const lim=limitOf(i);if(!lim)return false;
 let q=qnorm(pose.q[i]);
 if(q[0]<0)q=q.map(v=>-v);
 // разложение «скрутка вокруг оси кости + отклонение»: q = swing * twist
 const a=BAX[i]||[0,1,0];
 const proj=q[1]*a[0]+q[2]*a[1]+q[3]*a[2];
 let tw=[q[0],a[0]*proj,a[1]*proj,a[2]*proj];
 const tl=Math.hypot(...tw);
 tw=tl>1e-9?tw.map(v=>v/tl):[1,0,0,0];
 const sw=qnorm(qmul(q,qcon(tw)));
 const sa=2*Math.acos(Math.min(1,Math.abs(sw[0])));
 const ta=2*Math.acos(Math.min(1,Math.abs(tw[0])));
 const smax=lim[0]*Math.PI/180,tmax=lim[1]*Math.PI/180;
 let ch=false,s2=sw,t2=tw;
 if(sa>smax){const k=Math.sin(smax/2)/Math.max(1e-9,Math.sin(sa/2));
  s2=qnorm([Math.cos(smax/2),sw[1]*k,sw[2]*k,sw[3]*k]);ch=true;}
 if(ta>tmax){const s=proj<0?-1:1,h=Math.sin(tmax/2)*s;
  t2=[Math.cos(tmax/2),a[0]*h,a[1]*h,a[2]*h];ch=true;}
 if(ch)pose.q[i]=qnorm(qmul(s2,t2));
 return ch;}
function clampPose(){
 if(!OPT.limits)return 0;
 let n=0;for(let i=0;i<B.length;i++)if(clampLocal(i))n++;
 evalPose(pose);return n;}
// удержать мировой поворот потомков независимо от галочки (для стопы за голенью)
function holdKids(i,fn){
 evalPose(pose);
 const kids=CHILDREN[i],saved=kids.map(k=>wQ[k].slice());
 fn();evalPose(pose);
 kids.forEach((k,n)=>{const p=B[k].parent;
  const bq=p<0?relQ[k]:qmul(wQ[p],relQ[k]);
  pose.q[k]=qnorm(qmul(qcon(bq),saved[n]));});
 evalPose(pose);}
// ---- библиотека стартовых поз ----
// наши имена в библиотеке -> роль -> кость целевого скелета
const OURROLE=(()=>{const m={root:"hips",spine_01:"spine1",spine_02:"spine2",
  chest:"spine3",neck:"neck",head:"head"};
 for(const s of["L","R"]){m["clavicle."+s]="clavicle."+s;m["upper_arm."+s]="upperarm."+s;
  m["forearm."+s]="forearm."+s;m["hand."+s]="hand."+s;m["thigh."+s]="thigh."+s;
  m["shin."+s]="shin."+s;m["foot."+s]="foot."+s;m["toe."+s]="toe."+s;}
 return m;})();
function applyLibPose(name){
 const p=POSELIB.poses&&POSELIB.poses[name];if(!p)return false;
 pose=newPose();
 const want={};
 POSELIB.bones.forEach((n,j)=>{const r=OURROLE[n];if(!r)return;
  const i=RB(r);if(i>=0)want[i]=p.dir[j];});
 const tw={};
 if(p.twist)POSELIB.bones.forEach((n,j)=>{const r=OURROLE[n];if(!r)return;
  const i=RB(r);if(i>=0&&p.twist[j])tw[i]=p.twist[j];});
 for(const i of ORDER){
  const d=want[i];
  if(!d)continue;
  evalPose(pose);
  const h=head(i);
  pointBone(i,[h[0]+d[0]*B[i].length,h[1]+d[1]*B[i].length,h[2]+d[2]*B[i].length],true);
  // Скрутка вокруг собственной оси: направление её не несёт, а без неё ладони
  // остаются развёрнутыми вперёд, как в позе привязки.
  if(tw[i]){evalPose(pose);
   const ax=qrot(wQ[i],BAX[i]||[0,1,0]);
   applyWorld(pose,i,qaxis(ax,tw[i]*Math.PI/180));}}
 if(p.root_loc)pose.loc=p.root_loc.slice();
 clampPose();evalPose(pose);return true;}

function chainOf(e,depth){const c=[];let i=e;
 for(let k=0;k<depth&&i>=0;k++){c.push(i);i=B[i].parent;}return c;}
function chainReach(ch){evalPose(pose);let r=0;for(const b of ch)r+=B[b].length;
 return{S:head(ch[ch.length-1]).slice(),reach:r*0.999};}
function ccd(endI,target,depth,iters){
 const chain=chainOf(endI,depth);
 const{S,reach}=chainReach(chain);
 const t=[target[0]-S[0],target[1]-S[1],target[2]-S[2]],L=Math.hypot(...t);
 if(L>reach)target=[S[0]+t[0]*reach/L,S[1]+t[1]*reach/L,S[2]+t[2]*reach/L];
 for(let it=0;it<(iters||12);it++)for(const bi of chain){
  evalPose(pose);
  const e=tail(endI),p=head(bi);
  let a=[e[0]-p[0],e[1]-p[1],e[2]-p[2]],b=[target[0]-p[0],target[1]-p[1],target[2]-p[2]];
  const la=Math.hypot(...a),lb=Math.hypot(...b);
  if(la<1e-6||lb<1e-6)continue;
  applyWorld(pose,bi,qfromto(a.map(v=>v/la),b.map(v=>v/lb)));}
 evalPose(pose);}
function withHold(i,fn){
 if(!OPT.hold){fn();return;}
 evalPose(pose);const kids=CHILDREN[i],saved=kids.map(k=>wQ[k].slice());
 fn();evalPose(pose);
 kids.forEach((k,n)=>{const p=B[k].parent;
  const bq=p<0?relQ[k]:qmul(wQ[p],relQ[k]);
  pose.q[k]=qnorm(qmul(qcon(bq),saved[n]));});
 evalPose(pose);}

let HANDLES=[];
function draw(){
 resize();
 if(!MESH){bc.clearRect(0,0,bg.width,bg.height);
  oc.clearRect(0,0,ov.width,ov.height);
  gl.viewport(0,0,cv.width,cv.height);gl.clearColor(0,0,0,0);
  gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);return;}
 if(pose)evalPose(pose);
 VIEWS=views().map(v=>Object.assign({},v,{vp:vpFor(v)}));
 ACT=VIEWS.find(v=>v.dir===RS.dir)||VIEWS[0];
 bc.setTransform(1,0,0,1,0,0);bc.clearRect(0,0,bg.width,bg.height);
 bc.fillStyle="#0d0f11";bc.fillRect(0,0,bg.width,bg.height);
 if(RS.block)for(const v of VIEWS)blitRef(bc,RS.op,v);
 gl.viewport(0,0,cv.width,cv.height);
 gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
 if(document.getElementById("cMesh").checked){
  const mode=STEP===2?2:(document.getElementById("cTex").checked?1:0);
  setLight();
  gl.uniform1f(U.uMode,mode);
  gl.uniform1f(U.uHi,selBone>=0?selBone:0);
  gl.uniform1f(U.uSkin,SKIN?1:0);
  gl.uniform1f(U.uHasTex,TEX?1:0);
  if(TEX){gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,TEX);gl.uniform1i(U.uTex,0);}
  gl.uniformMatrix4fv(U.uB,false,B.length?skinMats():new Float32Array(16));
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,EB);
  for(const v of VIEWS){
   gl.viewport(v.rect.x,cv.height-v.rect.y-v.rect.h,v.rect.w,v.rect.h);
   gl.uniformMatrix4fv(U.uMVP,false,v.vp);
   gl.uniform3fv(U.uCam,new Float32Array(camPos(v.dir)));
   gl.drawElements(gl.TRIANGLES,NIDX,gl.UNSIGNED_INT,0);}
  gl.viewport(0,0,cv.width,cv.height);}
 oc.setTransform(1,0,0,1,0,0);oc.clearRect(0,0,ov.width,ov.height);
 // экипировка рисуется ПОВЕРХ модели: по рукояти меча и щиту видно, куда должна
 // прийти кисть — по одному силуэту тела это не читается
 if(RS.block&&RS.gear&&hasGear())for(const v of VIEWS)blitRef(oc,RS.gearOp,v,"gear");
 if(document.getElementById("cBones").checked&&B.length)overlay();
 if(skinStale){const d=window.devicePixelRatio||1;
  oc.fillStyle="rgba(74,43,30,.92)";oc.fillRect(0,0,ov.width,26*d);
  oc.fillStyle="#ffd9a8";oc.font="600 "+(13*d)+"px Segoe UI";
  oc.fillText("скелет изменён — веса устарели, пересчитаются при переходе к привязке",
              12*d,17*d);}
 if(RS.grid&&RS.block){const d=window.devicePixelRatio||1;oc.font=(12*d)+"px Segoe UI";
  for(const v of VIEWS){oc.fillStyle=v===ACT?"#6fd1ff":"rgba(180,190,205,.6)";
   oc.fillText(v.dir,v.rect.x+7*d,v.rect.y+15*d);
   oc.strokeStyle=v===ACT?"rgba(111,209,255,.5)":"rgba(120,130,145,.2)";
   oc.lineWidth=(v===ACT?2:1)*d;oc.strokeRect(v.rect.x+1,v.rect.y+1,v.rect.w-2,v.rect.h-2);}}}
function overlay(){
 const d=window.devicePixelRatio||1;HANDLES=[];
 for(const v of VIEWS){
  const act=v===ACT;
  evalPose(pose);
  const pts=[];
  for(let i=0;i<B.length;i++)pts[i]={h:projIn(head(i),v.vp,v.rect),t:projIn(tail(i),v.vp,v.rect)};
  oc.lineWidth=2*d;
  for(let i=0;i<B.length;i++){const a=pts[i].h,b=pts[i].t;if(!a||!b)continue;
   oc.strokeStyle=B[i].deform?(act?"rgba(224,164,88,.85)":"rgba(224,164,88,.4)")
                             :"rgba(140,150,165,.35)";
   oc.beginPath();oc.moveTo(a[0],a[1]);oc.lineTo(b[0],b[1]);oc.stroke();}
  if(!act)continue;
  if(STEP===1){                                  // шаг «скелет» — тянем сами суставы
   for(const k in J){const p=projIn(J[k],v.vp,v.rect);if(!p)continue;
    HANDLES.push({key:k,x:p[0],y:p[1]});
    const on=k===selJoint;
    oc.beginPath();oc.arc(p[0],p[1],(on?7:4.5)*d,0,7);
    oc.fillStyle=on?"#6fd1ff":(k.endsWith("R")?"#b9752f":"#e0a458");
    oc.fill();oc.lineWidth=1.5*d;oc.strokeStyle="#10131a";oc.stroke();}
   if(selJoint){oc.fillStyle="#6fd1ff";oc.font=(12*d)+"px Segoe UI";
    const p=projIn(J[selJoint],v.vp,v.rect);
    if(p)oc.fillText(RU[selJoint.replace(/[LR]$/,"")]||selJoint,p[0]+11*d,p[1]-9*d);
    drawGizmo(J[selJoint]);}
  }else{                                         // остальные шаги — тянем кости
   for(let i=0;i<B.length;i++){const t=pts[i].t;if(!t)continue;
    HANDLES.push({i,x:t[0],y:t[1]});
    const on=i===selBone;
    oc.beginPath();oc.arc(t[0],t[1],(on?7:4.5)*d,0,7);
    oc.fillStyle=on?"#6fd1ff":(NAMES[i].endsWith(".R")?"#b9752f":"#e0a458");
    oc.fill();oc.lineWidth=1.5*d;oc.strokeStyle="#10131a";oc.stroke();}
   if(selBone>=0&&pts[selBone].t){oc.fillStyle="#6fd1ff";oc.font=(12*d)+"px Segoe UI";
    oc.fillText(NAMES[selBone],pts[selBone].t[0]+11*d,pts[selBone].t[1]-9*d);
    if(STEP===3){if(OPT.tool==="rot")drawRotGizmo(head(selBone));
                 else drawGizmo(tail(selBone));}}}}}
</script>
<script>
// ============================================================ ввод
cv.addEventListener("contextmenu",e=>e.preventDefault());
cv.addEventListener("mousedown",e=>{
 if(!MESH)return;
 const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;
 const mx=(e.clientX-r.left)*d,my=(e.clientY-r.top)*d;
 if(e.button===2||e.button===1){
  if(isoOn())return;
  orbit={x:e.clientX,y:e.clientY,az:C.az,el:C.el,tx:C.tx,ty:C.ty,tz:C.tz,pan:e.shiftKey};return;}
 const v=viewAt(mx,my);
 if(v&&v!==ACT){RS.dir=v.dir;const s=document.getElementById("refDir");if(s)s.value=v.dir;draw();}
 // вращение: кольца имеют приоритет, пока выбран инструмент «вращать»
 if(STEP===3&&OPT.tool==="rot"&&selBone>=0){
  evalPose(pose);
  const piv=head(selBone).slice();
  const r=hitRot(mx,my,piv);
  if(r){const a0=ringAngle(ACT,mx,my,piv,r);
   if(a0!==null){drag={rot:{axis:r.a,ring:r,piv,a0,deg:0},i:selBone,
                       start:clonePose(pose)};draw();return;}}}
 const P=STEP===1?(selJoint?J[selJoint]:null):(selBone>=0?tail(selBone):null);
 const ax=(P&&!(STEP===3&&OPT.tool==="rot"))?hitAxis(mx,my,P):null;
 if(ax){const s0=axisParam(ACT,mx,my,P,ax.v);
  if(s0!==null){drag={axis:ax,J0:P.slice(),s0,
   key:STEP===1?selJoint:null,i:STEP===1?-1:selBone,depth:OPT.chain};draw();return;}}
 let best=null,bd=18*d;
 for(const h of HANDLES){const dd=Math.hypot(h.x-mx,h.y-my);if(dd<bd){bd=dd;best=h;}}
 if(!best)return;
 if(STEP===1){selJoint=best.key;
  const A=axisLock?AXES.find(a=>a.n===axisLock):null;
  drag={key:best.key,i:-1,axis:A,J0:J[best.key].slice(),
        s0:A?axisParam(ACT,mx,my,J[best.key],A.v):0};}
 else{selBone=best.i;
  const A=axisLock?AXES.find(a=>a.n===axisLock):null;
  evalPose(pose);const Jp=tail(best.i).slice();
  // Захват: запоминаем, НАСКОЛЬКО курсор промахнулся мимо точки, и держим это
  // смещение всё перетаскивание. Без него конечность прыгает под курсор рывком.
  const hit=rayPoint(ACT,mx,my,Jp);
  const off=[Jp[0]-hit[0],Jp[1]-hit[1],Jp[2]-hit[2]];
  const nm=NAMES[best.i];
  // синхронизируем полюс с фактическим локтем — иначе первый же кадр его дёрнет
  const limbKey=LIMB[nm]?nm:(POLEOF[nm]||null);
  if(limbKey){const cur=poleFromPose(limbKey);
   if(cur!==null)POLE[poleKey(limbKey)]=cur;}
  const pk=POLEOF[nm]?poleKey(POLEOF[nm]):null;
  drag={i:best.i,key:null,axis:A,J0:Jp,s0:A?axisParam(ACT,mx,my,Jp,A.v):0,
        depth:OPT.chain,off,
        poleBase:pk?POLE[pk]:0,
        poleA0:pk?poleAngleFromMouse(POLEOF[nm],ACT,mx,my):null};}
 panel();draw();});
window.addEventListener("mousemove",e=>{
 if(orbit){const dx=e.clientX-orbit.x,dy=e.clientY-orbit.y;
  if(orbit.pan){const s=C.dist*0.0022;
   C.tx=orbit.tx-Math.cos(C.az)*dx*s;C.ty=orbit.ty-Math.sin(C.az)*dx*s;C.tz=orbit.tz+dy*s;}
  else{C.az=orbit.az+dx*0.008;C.el=Math.max(-1.4,Math.min(1.4,orbit.el-dy*0.008));}
  draw();return;}
 if(!drag)return;
 const r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;
 const mx=(e.clientX-r.left)*d,my=(e.clientY-r.top)*d;
 if(drag.rot){                       // вращение вокруг мировой оси через начало кости
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
  draw();return;}
 let p;
 if(drag.axis){const s=axisParam(ACT,mx,my,drag.J0,drag.axis.v);
  if(s===null)return;
  let k=s-drag.s0;const A=drag.axis.v;
  if(drag.i>=0){const{S,reach}=chainReach(chainOf(drag.i,drag.depth));
   const w=[drag.J0[0]-S[0],drag.J0[1]-S[1],drag.J0[2]-S[2]];
   const b=A[0]*w[0]+A[1]*w[1]+A[2]*w[2];
   const disc=b*b-(w[0]*w[0]+w[1]*w[1]+w[2]*w[2]-reach*reach);
   if(disc>0){const rt=Math.sqrt(disc);k=Math.max(-b-rt,Math.min(-b+rt,k));}}
  p=[drag.J0[0]+A[0]*k,drag.J0[1]+A[1]*k,drag.J0[2]+A[2]*k];}
 else{evalPose(pose);
  p=rayPoint(ACT,mx,my,drag.key?J[drag.key]:tail(drag.i));
  if(drag.off)p=[p[0]+drag.off[0],p[1]+drag.off[1],p[2]+drag.off[2]];}
 if(drag.key){
  J[drag.key]=p.slice();
  if(OPT.sym&&/[LR]$/.test(drag.key)){
   const o=drag.key.slice(0,-1)+(drag.key.endsWith("L")?"R":"L");
   if(J[o])J[o]=[-p[0],p[1],p[2]];}
  if(CENTER.includes(drag.key))J[drag.key][0]=0;
  buildSkeleton();
  // Скелет поехал — прежние веса больше не про него. В позе покоя это не видно
  // (скин-матрицы всё равно единичные), а при первом же повороте меш растекается.
  if(SKIN)skinStale=true;}
 else{
  const nm=NAMES[drag.i];
  if(OPT.ik&&LIMB[nm]){                       // кисть/щиколотка — двухкостный IK
   // стопа не должна заваливаться вслед за голенью: держим её поворот в мире
   if(LIMB[nm][2]==="leg"&&OPT.footLock)holdKids(drag.i,()=>ik2(nm,p));
   else ik2(nm,p);
   // пределы во время IK НЕ применяем: они дёргают уже решённую цепь, а локоть
   // в двухкостном решении и так не выворачивается
  }else if(OPT.ik&&POLEOF[nm]){               // локоть/колено — доворот полюса
   const k=POLEOF[nm];
   const a=poleAngleFromMouse(k,ACT,mx,my);
   if(a!==null&&drag.poleA0!==null&&drag.poleA0!==undefined){
    let d=a-drag.poleA0;                      // ОТ текущего положения, а не в абсолют
    while(d>180)d-=360; while(d<-180)d+=360;
    POLE[poleKey(k)]=drag.poleBase+d;
    evalPose(pose);ik2(k,tail(IDX[LIMB[k][1]]).slice());}
  }else{
   const feet=(OPT.pinFeet&&affectsLegs(drag.i))?ankles():null;
   withHold(drag.i,()=>{
    if(!OPT.ik){
     evalPose(pose);const h=head(drag.i),t=tail(drag.i);
     let a=[t[0]-h[0],t[1]-h[1],t[2]-h[2]],b=[p[0]-h[0],p[1]-h[1],p[2]-h[2]];
     const la=Math.hypot(...a),lb=Math.hypot(...b);
     if(la>1e-6&&lb>1e-6)applyWorld(pose,drag.i,qfromto(a.map(v=>v/la),b.map(v=>v/lb)));}
    else ccd(drag.i,p,drag.depth);});
   if(feet)replantFeet(feet);
   clampPose();}}
 draw();});
window.addEventListener("mouseup",()=>{drag=null;orbit=null;});
cv.addEventListener("wheel",e=>{e.preventDefault();
 if(isoOn()){RS.zoom=Math.max(1,Math.min(8,RS.zoom*(e.deltaY<0?1.12:1/1.12)));
  const s=document.getElementById("refZoom");if(s)s.value=Math.round(RS.zoom*10);draw();return;}
 C.dist=Math.max(0.2,Math.min(40,C.dist*(e.deltaY<0?1/1.12:1.12)));draw();},{passive:false});
document.addEventListener("keydown",e=>{
 if(/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName))return;
 const ax={x:"X",y:"Y",z:"Z",ч:"X",н:"Y",я:"Z"}[e.key.toLowerCase()];
 if(ax){axisLock=axisLock===ax?null:ax;panel();draw();e.preventDefault();return;}
 if(e.key==="Escape"){axisLock=null;panel();draw();}});
window.addEventListener("resize",draw);
for(const id of["cMesh","cBones","cTex"])document.getElementById(id).onchange=draw;
</script>
<script>
// ============================================================ загрузка файлов
const busy=(t)=>{const b=document.getElementById("busy");
 document.getElementById("busytx").textContent=t||"";
 b.classList.toggle("on",!!t);};
function handleFiles(list){
 for(const f of list){
  if(/\.glb$/i.test(f.name)){
   busy("читаю "+f.name+"…");
   f.arrayBuffer().then(buf=>setTimeout(()=>{try{loadModel(buf,f.name);}
    catch(err){busy("");alert("не читается: "+err.message);}},30));}
  else if(/\.(png|jpe?g)$/i.test(f.name))setTimeout(()=>setTexture(f),0);}}
document.getElementById("file").onchange=e=>handleFiles(e.target.files);
const view=document.getElementById("view");
["dragenter","dragover"].forEach(t=>view.addEventListener(t,e=>{e.preventDefault();}));
view.addEventListener("drop",e=>{e.preventDefault();handleFiles(e.dataTransfer.files);});

let STATS={};
function loadModel(buf,name){
 const g=parseGLB(buf);
 const t0=performance.now();
 RIGGED=!!g.skin;
 // Со своим скиннингом варить вершины незачем: сварка нужна была только для
 // сглаживания весов, а веса тут уже есть и лучше моих.
 const w=RIGGED?{map:null,wpos:null,count:g.pos.length/3}:weld(g.pos,1e-5);
 MESH={pos:g.pos,nor:g.nor,uv:g.uv,idx:g.idx,w};
 if(!RIGGED)buildNeighbours();
 let z0=1e9,z1=-1e9;
 for(let i=2;i<g.pos.length;i+=3){if(g.pos[i]<z0)z0=g.pos[i];if(g.pos[i]>z1)z1=g.pos[i];}
 Z_FEET=z0;HGT=z1-z0;
 C.tz=(z0+z1)/2;C.dist=HGT*1.8;C.tx=C.ty=0;
 STATS={name,gen:g.gen,verts:g.pos.length/3,tris:g.idx.length/3,welded:w.count,
        merged:g.pos.length/3-w.count,H:HGT,ms:Math.round(performance.now()-t0),
        rigged:RIGGED};
 // шейдер под фактическое число костей — ДО заливки буферов
 const need=RIGGED?g.skin.joints.length:SPEC.length;
 STATS.shaderBones=buildProgram(need);
 if(need>STATS.shaderBones)
  console.warn("костей больше, чем помещается в шейдер:",need,">",STATS.shaderBones);
 uploadMesh();
 if(g.img)setTexture(g.img);
 PROXY=null;
 if(RIGGED){
  const nb=buildFromSkin(g.skin);
  SKIN={idx:g.skin.si,wt:g.skin.sw,perBone:{},welded:g.pos.length/3};
  uploadSkin();skinStale=false;
  STATS.bones=nb;STATS.roles=Object.keys(ROLE).length;
  J={};                                        // свои суставы не нужны
  document.getElementById("drop").classList.add("hide");
  busy("");go(3);                              // сразу к позе
 }else{
  J=autoJoints(g.pos);
  buildSkeleton();
  SKIN=null;
  document.getElementById("drop").classList.add("hide");
  busy("");go(1);}}
</script>
<script>
// ============================================================ поза из файла
let CLIP=null;
function loadClip(txt){
 const o=JSON.parse(txt);
 if(!o.bones||!o.keys)throw new Error("не похоже на позу из редактора");
 const miss=o.bones.filter(n=>IDX[n]===undefined);
 CLIP={name:o.name||"поза",bones:o.bones,keys:o.keys,fps:o.fps||24,
       length:o.length||Math.max(...Object.keys(o.keys).map(Number)),
       frames:Object.keys(o.keys).map(Number).sort((a,b)=>a-b),miss};
 // Габариты — часть подгонки: без них та же поза даст спрайты другого размера.
 // У файлов из редактора анимаций поля нет, поэтому строго по наличию.
 if(o.dims){RS.sw=+o.dims.width||1;RS.sh=+o.dims.height||1;RS.dy=+o.dims.dy||0;}
 applyClipFrame(CLIP.frames[0]);
 return CLIP;}
function applyClipFrame(f){
 const k=CLIP&&CLIP.keys[f];if(!k)return;
 pose=newPose();
 CLIP.bones.forEach((n,i)=>{const b=IDX[n];
  if(b!==undefined&&k.q[i])pose.q[b]=k.q[i].slice();});
 if(k.loc)pose.loc=k.loc.slice();
 CLIP.cur=f;evalPose(pose);}
// Поза выгружается в ДВУХ видах сразу. Локальные кватернионы (bones+keys) —
// чтобы студия открыла её обратно один в один тем же загрузчиком. Мировые
// направления костей (dir) — чтобы перенести на ЧУЖОЙ риг: у Mixamo своя поза
// покоя, локальные углы там дадут другую позу, а направления — ту же самую.
function poseJSON(){
 evalPose(pose);
 const dir={};
 for(const n in OURROLE){
  const i=RB(OURROLE[n]);if(i<0)continue;
  const h=head(i),t=tail(i);
  const v=[t[0]-h[0],t[1]-h[1],t[2]-h[2]],L=Math.hypot(v[0],v[1],v[2])||1;
  dir[n]=v.map(c=>+(c/L).toFixed(6));}
 const r6=a=>a.map(c=>+c.toFixed(6));
 return{name:(RS.block?RS.block+" кадр "+((OPT.fitFrame|0)||1):"поза"),
  fps:24,length:1,
  bones:B.map(b=>b.name),
  keys:{1:{q:pose.q.map(r6),loc:r6(pose.loc)}},
  dir,
  dims:{width:RS.sw,height:RS.sh,dy:RS.dy},
  rig:{model:STATS.name||"—",bones:B.length,skinned:!!SKIN},
  note:"keys — локальные кватернианы для этого же рига (грузится обратно в студию); "+
       "dir — мировые направления костей для переноса на другой скелет"};}
function downloadPose(){
 const o=poseJSON();
 const b=new Blob([JSON.stringify(o,null,1)],{type:"application/json"});
 const a=document.createElement("a");a.href=URL.createObjectURL(b);
 a.download=(STATS.name||"поза").replace(/\.(glb|gltf)$/i,"")+"_poza.json";
 a.click();
 return o;}
function clipPoses(){                       // все ключи как готовые позы
 if(!CLIP)return[pose];
 const save=clonePose(pose),out=[];
 for(const f of CLIP.frames){applyClipFrame(f);out.push(clonePose(pose));}
 pose=save;evalPose(pose);
 return out;}

// ============================================================ нарезка спрайтов
function renderSprites(cell,px,withTex,poses){
 const dirs=REF.dirs;
 poses=(poses&&poses.length)?poses:[pose];
 const out=document.createElement("canvas");
 out.width=cell*dirs.length;out.height=cell*poses.length;
 const g=out.getContext("2d");
 const tmp=document.createElement("canvas");tmp.width=tmp.height=cell;
 const saveW=cv.width,saveH=cv.height;
 cv.width=cell;cv.height=cell;
 gl.viewport(0,0,cell,cell);
 const t=REF.tilt*Math.PI/180;
 const anchor=[cell/2,cell*ANCHOR_FRAC];
 setLight();
 gl.uniform1f(U.uMode,withTex&&TEX?1:0);
 gl.uniform1f(U.uSkin,SKIN?1:0);
 gl.uniform1f(U.uHasTex,TEX?1:0);
 if(TEX){gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,TEX);gl.uniform1i(U.uTex,0);}
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,EB);
 const c2=tmp.getContext("2d");
 poses.forEach((ps,rowI)=>{
  evalPose(ps);
  gl.uniformMatrix4fv(U.uB,false,skinMats());
  dirs.forEach((d,i)=>{
   const a=(REF.az[d]||0)*Math.PI/180,D=20;
   const e=[D*Math.cos(t)*Math.sin(a),-D*Math.cos(t)*Math.cos(a),Z_FEET+D*Math.sin(t)];
   const vp=withScl(m4mul(ortho(cell/px,cell/px,0.1,80,0,oyFor(px,cell)),
                          lookAt(e,[0,0,Z_FEET],[0,0,1])));
   gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
   gl.uniformMatrix4fv(U.uMVP,false,vp);
   gl.uniform3fv(U.uCam,new Float32Array(e));
   gl.drawElements(gl.TRIANGLES,NIDX,gl.UNSIGNED_INT,0);
   c2.clearRect(0,0,cell,cell);c2.drawImage(cv,0,0);
   g.drawImage(tmp,i*cell,rowI*cell);});});
 cv.width=saveW;cv.height=saveH;
 if(pose)evalPose(pose);
 draw();
 return{canvas:out,cell,anchor,dirs:dirs.slice(),px,rows:poses.length};}
function downloadSheet(){
 const cell=OPT.cell,px=OPT.scale||REF.px_per_unit;
 const poses=(OPT.allFrames&&CLIP)?clipPoses():[pose];
 const r=renderSprites(cell,px,document.getElementById("cTex").checked,poses);
 const base=(STATS.name||"sprites").replace(/\.glb$/i,"")+
   (poses.length>1?"_"+(CLIP?CLIP.name:"clip"):"_pose");
 r.canvas.toBlob(b=>{const a=document.createElement("a");
  a.href=URL.createObjectURL(b);a.download=base+"_"+cell+".png";a.click();});
 const meta={cell,px_per_unit:px,anchor:r.anchor,dirs:r.dirs,tilt:REF.tilt,
   model:STATS.name,rows:r.rows,
   frames:(poses.length>1&&CLIP)?CLIP.frames:[1],
   note:"столбцы — направления в порядке dirs, строки — кадры; anchor — точка ног в клетке"};
 const b=new Blob([JSON.stringify(meta,null,1)],{type:"application/json"});
 const a=document.createElement("a");a.href=URL.createObjectURL(b);
 a.download=(STATS.name||"sprites").replace(/\.glb$/i,"")+".json";
 setTimeout(()=>a.click(),400);}
</script>
<script>
// ============================================================ подбор позы под эталон
// Один ракурс позу не определяет — за плоским силуэтом прячется бесконечно много
// трёхмерных поз. Восемь ракурсов сразу задачу закрывают. Считаем среднее
// пересечение силуэтов по всем восьми и ищем максимум простым (1+1)-поиском:
// пошевелили несколько костей — стало лучше, оставили; хуже — откатили.
let FIT=null,PROXY=null;
// Силуэту миллион треугольников не нужен. Сгущаем вершины в кубическую сетку и
// оставляем те треугольники, у которых углы попали в РАЗНЫЕ ячейки. Буферы вершин
// те же самые — меняется только список индексов, так что скиннинг работает как был.
function buildFitProxy(){
 const P=MESH.pos,n=P.length/3;
 let lo=[1e9,1e9,1e9],hi=[-1e9,-1e9,-1e9];
 for(let i=0;i<n;i++)for(let k=0;k<3;k++){const v=P[i*3+k];
  if(v<lo[k])lo[k]=v;if(v>hi[k])hi[k]=v;}
 const size=Math.max(hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2]);
 const G=80,cs=size/G;
 const rep=new Map(),cellOf=new Int32Array(n);
 for(let i=0;i<n;i++){
  const a=Math.floor((P[i*3]-lo[0])/cs),b=Math.floor((P[i*3+1]-lo[1])/cs),
        c=Math.floor((P[i*3+2]-lo[2])/cs);
  const key=(a*1024+b)*1024+c;
  let r0=rep.get(key);
  if(r0===undefined){r0=i;rep.set(key,i);}
  cellOf[i]=r0;}
 const src=MESH.idx,out=[];
 for(let t=0;t<src.length;t+=3){
  const a=cellOf[src[t]],b=cellOf[src[t+1]],c=cellOf[src[t+2]];
  if(a===b||b===c||a===c)continue;
  out.push(a,b,c);}
 const arr=new Uint32Array(out);
 const eb=gl.createBuffer();
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,eb);
 gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,arr,gl.STATIC_DRAW);
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,EB);
 PROXY={eb,count:arr.length,tris:arr.length/3};
 return PROXY;}
function fitPrepare(block,frameIdx,cell){
 const k=cell/160, px=REF.px_per_unit*k;
 const w=REF.window;
 const masks=[],areas=[];
 const c=document.createElement("canvas");c.width=c.height=cell;
 const g=c.getContext("2d",{willReadFrequently:true});
 for(const d of REF.dirs){
  const im=refStrip(d);
  g.clearRect(0,0,cell,cell);
  if(im){g.imageSmoothingEnabled=false;
   g.drawImage(im,frameIdx*w.w,0,w.w,w.h,
     cell/2-w.ax*k, cell*ANCHOR_FRAC-w.ay*k, w.w*k, w.h*k);}
  const dd=g.getImageData(0,0,cell,cell).data;
  const m=new Uint8Array(cell*cell);let a=0;
  for(let i=0,j=3;i<m.length;i++,j+=4){if(dd[j]>8){m[i]=1;a++;}}
  masks.push(m);areas.push(a);}
 FIT={cell,px,masks,areas,buf:new Uint8Array(cell*cell*4)};
 return FIT;}
function fitScore(){
 const{cell,px,masks,buf}=FIT;
 const sw=cv.width,sh=cv.height;
 cv.width=cell;cv.height=cell;
 gl.viewport(0,0,cell,cell);
 gl.uniform1f(U.uMode,0);gl.uniform1f(U.uSkin,SKIN?1:0);gl.uniform1f(U.uHasTex,0);
 evalPose(pose);
 gl.uniformMatrix4fv(U.uB,false,skinMats());
 // Считаем по ПОЛНОЙ сетке. Огрублённая копия экономила лишь 2.3× (25 мс против
 // 58), но поиск начинал подгоняться под её дыры: на прокси 0.6445, на настоящем
 // меше та же поза давала 0.5952 — то есть весь прирост был мнимым.
 const pr={eb:EB,count:NIDX};
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,pr.eb);
 const t=REF.tilt*Math.PI/180;
 let sum=0;
 REF.dirs.forEach((d,i)=>{
  const a=(REF.az[d]||0)*Math.PI/180,D=20;
  const e=[D*Math.cos(t)*Math.sin(a),-D*Math.cos(t)*Math.cos(a),Z_FEET+D*Math.sin(t)];
  gl.uniformMatrix4fv(U.uMVP,false,
   withScl(m4mul(ortho(cell/px,cell/px,0.1,80,0,oyFor(px,cell)),lookAt(e,[0,0,Z_FEET],[0,0,1]))));
  gl.uniform3fv(U.uCam,new Float32Array(e));
  gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  gl.drawElements(gl.TRIANGLES,pr.count,gl.UNSIGNED_INT,0);
  gl.readPixels(0,0,cell,cell,gl.RGBA,gl.UNSIGNED_BYTE,buf);
  const m=masks[i];let inter=0,uni=0;
  // readPixels отдаёт снизу вверх — маску строили сверху, поэтому переворачиваем строку
  for(let y=0;y<cell;y++){
   const src=(cell-1-y)*cell, dst=y*cell;
   for(let x=0;x<cell;x++){
    const ours=buf[(src+x)*4+3]>8?1:0, ref=m[dst+x];
    if(ours|ref){uni++;if(ours&ref)inter++;}}}
  sum+=uni?inter/uni:0;});
 cv.width=sw;cv.height=sh;
 return sum/REF.dirs.length;}
function fitStep(sigma){
 if(!FITB.length)return[];
 const n=1+Math.floor(Math.random()*3);
 const touched=[];
 for(let k=0;k<n;k++){
  const e=FITB[Math.floor(Math.random()*FITB.length)];
  const i=IDX[e[0]];if(i===undefined)continue;
  touched.push([i,pose.q[i].slice()]);
  const ax=[Math.random()*2-1,Math.random()*2-1,Math.random()*2-1];
  const l=Math.hypot(...ax)||1;
  const ang=(Math.random()*2-1)*sigma*e[1];
  pose.q[i]=qnorm(qmul(pose.q[i],qaxis(ax.map(c=>c/l),ang)));
  if(OPT.limits)clampLocal(i);}
 return touched;}
function fitRun(opts,done){
 const total=opts.iters||400;
 let sigma=opts.sigma||0.14, best=fitScore(), it=0, good=0, idle=0;
 const t0=performance.now();
 const chunk=()=>{
  const end=Math.min(total,it+12);
  for(;it<end;it++){
   const undo=fitStep(sigma);
   const s=fitScore();
   if(s>best){best=s;good++;idle=0;}
   else{for(const[i,q]of undo)pose.q[i]=q;idle++;}
   if(it%25===24){                       // правило 1/5: держим долю удач около 20%
    sigma*= (good/25>0.2)?1.25:0.85;
    // Нижняя граница обязательна: без неё шаг усыхает до долей градуса и поиск
    // залипает в первом же локальном максимуме — 600 проб подряд впустую.
    sigma=Math.max(0.035,Math.min(0.45,sigma));good=0;}
   if(idle>=130){sigma=0.16;idle=0;}}    // встряска, если долго нет улучшений
  evalPose(pose);
  opts.onstep&&opts.onstep(it,total,best,sigma);
  if(it<total)setTimeout(chunk,0);
  else polish(0);};
 // Доводка мелким шагом: основной проход ищет широко, этот — подчищает.
 const NP=opts.polish===undefined?70:opts.polish;
 let pbest=null;
 const polish=(k)=>{
  if(k===0)pbest=fitScore();
  const end=Math.min(NP,k+6);
  for(;k<end;k++){
   const undo=fitStep(0.05);
   const s=fitScore();
   if(s>pbest)pbest=s; else for(const[i,q]of undo)pose.q[i]=q;}
  evalPose(pose);
  opts.onstep&&opts.onstep(total+k,total+NP,pbest,0.05);
  if(k<NP)setTimeout(()=>polish(k),0);
  else done&&done(pbest,Math.round(performance.now()-t0));};
 chunk();}

// ============================================================ панели шагов
function go(s){STEP=s;
 if(s===3||s===4){RS.iso=true;if(!RS.block)RS.block="stand";}
 else RS.iso=false;
 if(RIGGED&&(s===1||s===2))s=3;                 // свой риг: скелет и веса уже готовы
 if(!RIGGED&&s>=2&&(!SKIN||skinStale))recalcWeights();
 document.querySelectorAll(".step").forEach(el=>{
  const n=+el.dataset.step;
  el.classList.toggle("act",n===s);
  el.classList.toggle("done",(n===0&&MESH)||(n===1&&B.length)||(n===2&&SKIN));});
 panel();draw();}
document.querySelectorAll(".step").forEach(el=>el.onclick=()=>{if(MESH||+el.dataset.step===0)go(+el.dataset.step);});
function recalcWeights(){
 if(!MESH)return;
 busy("считаю веса…");
 setTimeout(()=>{
  const t0=performance.now();
  computeWeights(OPT.wPow,OPT.wSmooth);
  STATS.wms=Math.round(performance.now()-t0);
  busy("");panel();draw();},30);}
const H=s=>s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function panel(){
 const el=document.getElementById("panel");
 if(!MESH){el.innerHTML='<h3>Шаг 1 — модель</h3>'+
  '<div style="color:var(--dim)">Перетащи <b>.glb</b> в окно слева. '+
  'Если текстура отдельным файлом — брось её следом (png/jpg).<br><br>'+
  'Модель должна стоять в позе покоя (T или A), ногами на нуле, лицом на −Y.</div>';return;}
 let h="";
 if(STEP===0||STEP===1){
  h+='<h3>Модель</h3><table class="st">'+
   row("файл",H(STATS.name))+row("создано",H(STATS.gen))+
   row("вершин",STATS.verts.toLocaleString("ru"))+
   row("треугольников",STATS.tris.toLocaleString("ru"))+
   (STATS.rigged?row("скелет в файле",STATS.bones+" костей","ok")+
     row("роли опознаны",STATS.roles,STATS.roles>=18?"ok":"warn")+
     row("скиннинг","из файла","ok"):
     row("после сварки",STATS.welded.toLocaleString("ru"))+
     row("слито по швам",STATS.merged.toLocaleString("ru"),STATS.merged>0?"ok":""))+
   row("высота",STATS.H.toFixed(4))+
   row("разбор",STATS.ms+" мс")+
   row("текстура",TEX?"есть":"нет",TEX?"ok":"warn")+'</table>'+
   '<h3>Текстура</h3>'+
   '<div style="color:var(--dim);margin-bottom:5px">Если она отдельным файлом — выбери здесь '+
   'или просто брось png/jpg в окно слева.</div>'+
   '<input type="file" id="texFile" accept=".png,.jpg,.jpeg,.webp" style="width:100%">'+
   (TEX?'<div class="row" style="margin-top:6px"><span>показывать</span>'+
        '<button id="bTexOn" class="'+(document.getElementById("cTex").checked?"on":"")+
        '">текстура во вьюпорте</button></div>':"");}
 if(STEP===1){
  h+='<h3>Шаг 2 — скелет</h3>'+
   '<div style="color:var(--dim);margin-bottom:6px">Суставы расставлены автоматически по '+
   'обмерам. Поправь мышью: тяни точку, либо за цветную ось гизмо.</div>'+
   '<label class="chk"><input type="checkbox" id="cSym"'+(OPT.sym?" checked":"")+
   '> зеркалить правую от левой</label>'+
   '<div class="row"><span>ось</span><b id="axv">'+(axisLock||"свободно")+'</b></div>'+
   '<div class="grid" style="grid-template-columns:repeat(4,1fr)">'+
   ['X','Y','Z',''].map(a=>'<button data-ax="'+a+'"'+(axisLock===a?' class="on"':'')+'>'+
    (a||'своб.')+'</button>').join("")+'</div>'+
   (skinStale?'<div style="margin:8px 0;padding:7px 9px;border-radius:6px;'+
     'background:#4a2b1e;border:1px solid #8a5a2f;color:#ffd9a8">Скелет изменён — '+
     'веса устарели. Пересчитаются сами при переходе к привязке.</div>':"")+
   '<div class="grid" style="margin-top:6px"><button id="bAuto">пересчитать авто</button>'+
   '<button id="bDownJ">скачать joints.json</button></div>'+
   '<h3>Суставы</h3><div class="blist" id="jlist"></div>'+
   '<div class="grid" style="margin-top:8px"><button class="pri" id="bNext1">дальше — привязка</button></div>';}
 if(STEP===2){
  h+='<h3>Шаг 3 — привязка</h3>'+
   '<div style="color:var(--dim);margin-bottom:6px">Веса считаются по расстоянию до кости и '+
   'сглаживаются по рёбрам сваренной сетки. Цвет — вес выбранной кости.</div>'+
   '<div class="row"><span>жёсткость</span><input type="number" id="wPow" min="1" max="10" step="0.5" value="'+
   OPT.wPow+'"></div>'+
   '<div class="row"><span>сглаживание</span><input type="number" id="wSmooth" min="0" max="30" value="'+
   OPT.wSmooth+'"></div>'+
   '<button id="bW" style="width:100%">пересчитать веса</button>'+
   (SKIN?'<table class="st" style="margin-top:8px">'+
    row("сваренных вершин",SKIN.welded.toLocaleString("ru"))+
    row("костей влияет",Object.keys(SKIN.perBone).length)+
    row("счёт",(STATS.wms||0)+" мс")+'</table>':"")+
   '<h3>Кость (подсветка)</h3><div class="blist" id="blist"></div>'+
   '<div class="grid" style="margin-top:8px"><button class="pri" id="bNext2">дальше — поза</button></div>';}
 if(STEP===3){
  h+='<h3>Шаг 4 — поза</h3>'+
   '<div class="row"><span>инструмент</span>'+
   '<button id="tMove"'+(OPT.tool==="move"?' class="on"':'')+'>⇄ двигать</button>'+
   '<button id="tRot"'+(OPT.tool==="rot"?' class="on"':'')+'>⟳ вращать</button></div>'+
   (OPT.tool==="rot"?'<div style="color:var(--dim);margin:2px 0 6px">Кольца вокруг НАЧАЛА кости. '+
     'Shift при перетаскивании — шаг 5°. Кольцо, повёрнутое к нам ребром, гаснет.</div>':"")+
   '<div class="row"><span>режим</span><button id="mIK"'+(OPT.ik?' class="on"':'')+
   '>IK</button><button id="mFK"'+(OPT.ik?'':' class="on"')+'>FK</button></div>'+
   '<div style="color:var(--dim);margin:2px 0 6px;line-height:1.5">'+
   'В режиме IK точки работают как контролы:<br>'+
   '<b>запястье</b> и <b>щиколотка</b> — цель руки/ноги, решается формулой;<br>'+
   '<b>локоть</b> и <b>колено</b> — доворот полюса, крутят изгиб вокруг оси;<br>'+
   '<b>кисть</b> и <b>носок</b> — поворот на месте.<br>'+
   'Плечо и бедро сами не двигаются — корпус не уедет.</div>'+
   '<h3>Начать с готовой позы</h3>'+
   '<div style="color:var(--dim);margin-bottom:5px">Позы не лепят с нуля — берут '+
   'мокап и правят. Здесь кадры из оригинальной ходьбы игры.</div>'+
   '<select id="libSel" style="width:100%"><option value="">— выбрать —</option>'+
   Object.keys(POSELIB.poses||{}).map(k=>'<option>'+H(k)+'</option>').join("")+'</select>'+
   '<h3>Подобрать под эталон</h3>'+
   '<div style="color:var(--dim);margin-bottom:5px">Сравнивает силуэты во всех восьми '+
   'направлениях и подгоняет позу под них. Начинать лучше с близкой позы из библиотеки.</div>'+
   '<div class="row"><span>кадр эталона</span><input type="number" id="fitFrame" min="1" '+
   'max="'+(RS.block?REF.blocks[RS.block].frames:1)+'" value="'+(OPT.fitFrame||1)+'"></div>'+
   '<div class="row"><span>проб</span><input type="number" id="fitIters" min="50" max="4000" '+
   'step="50" value="'+OPT.fitIters+'"></div>'+
   '<button class="pri" id="bFit" style="width:100%"'+(RS.block?"":" disabled")+'>'+
   (RS.block?"подобрать позу":"сначала выбери подложку")+'</button>'+
   '<div id="fitOut" style="margin-top:6px;color:var(--dim)"></div>'+
   '<h3>Ограничения</h3>'+
   '<label class="chk"><input type="checkbox" id="cLim"'+(OPT.limits?" checked":"")+
   '> анатомические пределы суставов</label>'+
   '<label class="chk"><input type="checkbox" id="cFootLock"'+(OPT.footLock?" checked":"")+
   '> стопа не заваливается за голенью</label>'+
   '<label class="chk"><input type="checkbox" id="cPin"'+(OPT.pinFeet?" checked":"")+
   '> прибить стопы (корпус двигается, ноги остаются)</label>'+
   '<div class="row"><span>для прочих костей: родителей</span>'+
   '<input type="number" id="chain" min="1" max="5" value="'+OPT.chain+'"></div>'+
   '<label class="chk"><input type="checkbox" id="cHold"'+(OPT.hold?" checked":"")+
   '> дети сохраняют поворот</label>'+
   '<div class="row"><span>полюс локтей</span><b>'+
   POLE["arm.L"].toFixed(0)+'° / '+POLE["arm.R"].toFixed(0)+'°</b></div>'+
   '<div class="row"><span>полюс коленей</span><b>'+
   POLE["leg.L"].toFixed(0)+'° / '+POLE["leg.R"].toFixed(0)+'°</b></div>'+
   '<button id="bPole0" style="width:100%">полюса в ноль</button>'+
   '<div class="row"><span>ось</span><b id="axv">'+(axisLock||"свободно")+'</b></div>'+
   '<div class="grid" style="grid-template-columns:repeat(4,1fr)">'+
   ['X','Y','Z',''].map(a=>'<button data-ax="'+a+'"'+(axisLock===a?' class="on"':'')+'>'+
    (a||'своб.')+'</button>').join("")+'</div>'+
   '<h3>Эталон из игры</h3>'+
   '<div class="row"><span>подложка</span><select id="refBlock">'+
   ['','stand','walk','idle','run'].map(b=>'<option value="'+b+'"'+(RS.block===b?' selected':'')+'>'+
    ({"":"нет",stand:"стойка",walk:"ходьба",idle:"простой",run:"бег"}[b])+'</option>').join("")+
   '</select></div>'+
   '<div class="row"><span>направление</span><select id="refDir">'+
   REF.dirs.map(d=>'<option'+(RS.dir===d?' selected':'')+'>'+d+'</option>').join("")+'</select></div>'+
   '<div class="row"><span>прозрачность тела</span></div><input type="range" id="refOp" min="0" max="100" value="'+
   Math.round(RS.op*100)+'">'+
   '<label class="chk" style="margin-top:4px"><input type="checkbox" id="refGear"'+
   (RS.gear?" checked":"")+'> экипировка поверх модели</label>'+
   '<div style="color:var(--dim);font-size:11px;margin-bottom:2px">доспех, меч и щит из игры — '+
   'по рукояти видно, куда должна прийти кисть</div>'+
   '<input type="range" id="refGearOp" min="0" max="100" value="'+
   Math.round(RS.gearOp*100)+'">'+
   '<div class="row"><span>увеличение</span></div><input type="range" id="refZoom" min="10" max="80" value="'+
   Math.round(RS.zoom*10)+'">'+
   '<h3>Габариты под эталон</h3>'+
   '<div style="color:var(--dim);font-size:11px;margin-bottom:5px">действуют и на подгонку '+
   'позы, и на выгруженные спрайты</div>'+
   '<div class="row"><span>смещение по высоте</span><b id="vDy">'+RS.dy.toFixed(0)+' px</b></div>'+
   '<input type="range" id="refDy" min="-60" max="60" step="1" value="'+RS.dy+'">'+
   '<div class="row"><span>ширина персонажа</span><b id="vSw">'+Math.round(RS.sw*100)+'%</b></div>'+
   '<input type="range" id="refSw" min="50" max="180" step="1" value="'+Math.round(RS.sw*100)+'">'+
   '<div class="row"><span>высота персонажа</span><b id="vSh">'+Math.round(RS.sh*100)+'%</b></div>'+
   '<input type="range" id="refSh" min="50" max="180" step="1" value="'+Math.round(RS.sh*100)+'">'+
   '<button id="bDimReset" style="margin-top:5px">сбросить габариты</button>'+
   '<div class="grid" style="margin-top:6px"><button id="bGrid"'+(RS.grid?' class="on"':'')+
   '>все направления</button><button id="bRest">поза в покой</button></div>'+
   '<h3>Поза из файла</h3>'+
   '<div style="color:var(--dim);margin-bottom:5px">json из редактора анимаций — кости '+
   'сопоставляются по именам, ставить руками ничего не нужно.</div>'+
   '<input type="file" id="poseFile" accept=".json" style="width:100%">'+
   (CLIP?'<table class="st" style="margin-top:6px">'+
     row("клип",H(CLIP.name))+row("кадров",CLIP.frames.length)+
     row("не нашлось костей",CLIP.miss.length,CLIP.miss.length?"warn":"ok")+'</table>'+
     '<div class="row"><span>кадр</span><select id="clipFrame">'+
     CLIP.frames.map(f=>'<option'+(f===CLIP.cur?' selected':'')+'>'+f+'</option>').join("")+
     '</select></div>':"")+
   lightPanel()+
   '<h3>Кости</h3><div class="blist" id="blist"></div>'+
   '<div class="grid" style="margin-top:8px"><button class="pri" id="bNext3">дальше — спрайты</button></div>';}
 if(STEP===4){
  h+='<h3>Шаг 5 — спрайты</h3>'+
   '<div class="row"><span>клетка, px</span><input type="number" id="cellPx" min="64" max="512" step="8" value="'+
   OPT.cell+'"></div>'+
   '<div class="row"><span>px на единицу</span><input type="number" id="scalePx" min="5" max="400" step="0.01" value="'+
   (OPT.scale||REF.px_per_unit)+'"></div>'+
   '<div style="color:var(--dim);margin:6px 0">Масштаб игры — '+REF.px_per_unit+
   ' px на мировую единицу, наклон камеры '+REF.tilt.toFixed(2)+'°. '+
   'Столбцы — направления: '+REF.dirs.join(", ")+'.</div>'+
   (CLIP?'<label class="chk"><input type="checkbox" id="cAllFrames"'+(OPT.allFrames?" checked":"")+
     '> все кадры клипа «'+
     H(CLIP.name)+'» ('+CLIP.frames.length+' строк)</label>':
     '<div style="color:var(--dim)">Клип не загружен — уйдёт одна строка с текущей позой. '+
     'Загрузить json можно на шаге «поза».</div>')+
   '<h3>Поза из файла</h3>'+
   '<input type="file" id="poseFile" accept=".json" style="width:100%">'+
   '<button class="pri" id="bSheet" style="width:100%;margin-top:8px">сгенерировать и скачать</button>'+
   '<div id="prev" style="margin-top:10px"></div>'+
   lightPanel();}
 if(B.length)h+=
  '<h3>Сохранить позу</h3>'+
  '<div style="color:var(--dim);font-size:11px;margin-bottom:5px">Файл кладётся обратно '+
  'в «Поза из файла» и открывается один в один. Внутри же лежат мировые направления '+
  'костей — ими поза переносится на любой другой скелет.</div>'+
  '<button class="pri" id="bPose" style="width:100%">скачать позу json</button>'+
  '<div id="poseOut" style="color:var(--dim);font-size:11px;margin-top:4px"></div>';
 el.innerHTML=h;
 wire();wireLight();}
const row=(a,b,cls)=>'<tr><td>'+a+'</td><td'+(cls?' class="'+cls+'"':'')+'>'+b+'</td></tr>';
// ---- освещение модели ----
const LSL=[["gain","яркость",0,150,100],["amb","заполняющий",0,100,100],
           ["rim","контур",0,60,100],["spec","блик",0,80,100],
           ["az","азимут",0,360,1],["el","высота",-20,90,1]];
function lightPanel(){
 const L=OPT.light;
 return '<h3>Освещение</h3>'+
  '<label class="chk"><input type="checkbox" id="lFollow"'+(L.follow?" checked":"")+
  '> свет от камеры</label>'+
  LSL.map(([k,t,mn,mx,sc])=>
   '<div class="row" style="margin:4px 0 0"><span>'+t+'</span>'+
   '<b id="lv_'+k+'" style="flex:0">'+(sc===1?Math.round(L[k])+"°":L[k].toFixed(2))+'</b></div>'+
   '<input type="range" id="ls_'+k+'" min="'+mn+'" max="'+mx+'" value="'+
   Math.round(L[k]*sc)+'"'+((k==="az"||k==="el")&&L.follow?" disabled":"")+'>').join("")+
  '<button id="lReset" style="width:100%;margin-top:6px">сброс освещения</button>';}
function wireLight(){
 const q=id=>document.getElementById(id);
 const f=q("lFollow");
 if(f)f.onchange=e=>{OPT.light.follow=e.target.checked;panel();draw();};
 for(const[k,t,mn,mx,sc] of LSL){
  const s=q("ls_"+k);if(!s)continue;
  s.oninput=e=>{OPT.light[k]=+e.target.value/sc;
   const v=q("lv_"+k);
   if(v)v.textContent=sc===1?Math.round(OPT.light[k])+"°":OPT.light[k].toFixed(2);
   draw();};}
 if(q("lReset"))q("lReset").onclick=()=>{
  OPT.light={follow:true,az:35,el:45,amb:0.32,gain:0.70,rim:0.14,spec:0.0};
  panel();draw();};}
function wire(){
 const q=id=>document.getElementById(id);
 // всё, что переживает перерисовку панели, читаем и пишем через OPT
 const bind=(id,key,kind)=>{const el=q(id);if(!el)return;
  el.onchange=e=>{OPT[key]=kind==="b"?e.target.checked:+e.target.value;};};
 bind("cSym","sym","b");bind("cHold","hold","b");bind("cAllFrames","allFrames","b");
 bind("cPin","pinFeet","b");bind("cLim","limits","b");bind("cFootLock","footLock","b");
 if(q("bPole0"))q("bPole0").onclick=()=>{for(const k in POLE)POLE[k]=0;panel();draw();};
 if(q("libSel"))q("libSel").onchange=e=>{
  if(e.target.value){applyLibPose(e.target.value);draw();}};
 bind("fitIters","fitIters");bind("fitFrame","fitFrame");
 if(q("bFit"))q("bFit").onclick=()=>{
  if(!RS.block||!SKIN)return;
  const n=REF.blocks[RS.block].frames;
  const fr=Math.max(1,Math.min(n,OPT.fitFrame||1));
  fitPrepare(RS.block,fr-1,96);
  const out=q("fitOut");
  const start=fitScore();
  q("bFit").disabled=true;
  fitRun({iters:OPT.fitIters,onstep:(i,t,b,s)=>{
    out.innerHTML="проба "+i+" из "+t+"<br>совпадение "+b.toFixed(3)+
                  " (было "+start.toFixed(3)+")<br>шаг "+(s*57.3).toFixed(1)+"°";
    draw();},
   },(best,ms)=>{
    out.innerHTML="<b style='color:var(--ok)'>готово</b><br>совпадение "+
      start.toFixed(3)+" → <b>"+best.toFixed(3)+"</b><br>за "+(ms/1000).toFixed(1)+" с";
    q("bFit").disabled=false;draw();});};
 bind("chain","chain");bind("wPow","wPow");bind("wSmooth","wSmooth");
 bind("cellPx","cell");bind("scalePx","scale");
 document.querySelectorAll("[data-ax]").forEach(b=>b.onclick=()=>{
  axisLock=b.dataset.ax||null;panel();draw();});
 if(q("bAuto"))q("bAuto").onclick=()=>{J=autoJoints(MESH.pos);buildSkeleton();
  SKIN=null;skinStale=false;panel();draw();};
 if(q("bDownJ"))q("bDownJ").onclick=()=>{
  const o={common:{},L:{},R:{}};
  for(const k of CENTER)o.common[k]=J[k].map(v=>+v.toFixed(4));
  for(const s of["L","R"])for(const k of SIDED)o[s][k]=J[k+s].map(v=>+v.toFixed(4));
  const b=new Blob([JSON.stringify(o,null,1)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(b);
  a.download="joints.json";a.click();};
 if(q("jlist")){
  const keys=CENTER.concat(SIDED.map(k=>k+"L"),SIDED.map(k=>k+"R"));
  q("jlist").innerHTML=keys.map(k=>'<div class="bi'+(k===selJoint?" sel":"")+'" data-j="'+k+'">'+
   (RU[k.replace(/[LR]$/,"")]||k)+(/[LR]$/.test(k)?" "+k.slice(-1):"")+'</div>').join("");
  q("jlist").querySelectorAll("[data-j]").forEach(e=>e.onclick=()=>{
   selJoint=e.dataset.j;panel();draw();});}
 if(q("blist")){
  q("blist").innerHTML=NAMES.map((n,i)=>'<div class="bi'+(i===selBone?" sel":"")+
   (B[i].deform?"":" ctl")+'" data-b="'+i+'">'+n+'</div>').join("");
  q("blist").querySelectorAll("[data-b]").forEach(e=>e.onclick=()=>{
   selBone=+e.dataset.b;panel();draw();});}
 if(q("bW"))q("bW").onclick=recalcWeights;
 if(q("bNext1"))q("bNext1").onclick=()=>go(2);
 if(q("bNext2"))q("bNext2").onclick=()=>go(3);
 if(q("bNext3"))q("bNext3").onclick=()=>go(4);
 if(q("mIK"))q("mIK").onclick=()=>{OPT.ik=true;panel();};
 if(q("mFK"))q("mFK").onclick=()=>{OPT.ik=false;panel();};
 if(q("tMove"))q("tMove").onclick=()=>{OPT.tool="move";panel();draw();};
 if(q("tRot"))q("tRot").onclick=()=>{OPT.tool="rot";panel();draw();};
 if(q("bRest"))q("bRest").onclick=()=>{pose=newPose();draw();};
 if(q("refBlock"))q("refBlock").onchange=e=>{RS.block=e.target.value;draw();};
 if(q("refDir"))q("refDir").onchange=e=>{RS.dir=e.target.value;draw();};
 if(q("refOp"))q("refOp").oninput=e=>{RS.op=+e.target.value/100;draw();};
 if(q("refGear"))q("refGear").onchange=e=>{RS.gear=e.target.checked;draw();};
 if(q("refGearOp"))q("refGearOp").oninput=e=>{RS.gearOp=+e.target.value/100;draw();};
 if(q("refZoom"))q("refZoom").oninput=e=>{RS.zoom=+e.target.value/10;draw();};
 // Габариты меняют силуэт, по которому считается подгонка, поэтому старые маски
 // и отложенный расчёт скина сбрасывать не нужно — но перерисовать надо сразу.
 const dim=(id,lab,set)=>{const s=q(id);if(!s)return;
  s.oninput=e=>{set(+e.target.value);const t=q(lab);if(t)t.textContent=
   (id==="refDy")?RS.dy.toFixed(0)+" px":Math.round((id==="refSw"?RS.sw:RS.sh)*100)+"%";
   draw();};};
 dim("refDy","vDy",v=>{RS.dy=v;});
 dim("refSw","vSw",v=>{RS.sw=v/100;});
 dim("refSh","vSh",v=>{RS.sh=v/100;});
 if(q("bDimReset"))q("bDimReset").onclick=()=>{RS.dy=0;RS.sw=1;RS.sh=1;panel();draw();};
 if(q("bPose"))q("bPose").onclick=()=>{
  const o=downloadPose(),out=q("poseOut");
  if(out)out.innerHTML="сохранено: "+o.bones.length+" костей, "+
   Object.keys(o.dir).length+" направлений, габариты "+
   Math.round(o.dims.width*100)+"%/"+Math.round(o.dims.height*100)+"%";};
 if(q("bGrid"))q("bGrid").onclick=()=>{RS.grid=!RS.grid;
  if(RS.grid&&RS.zoom>2)RS.zoom=1.6;if(!RS.grid&&RS.zoom<2.5)RS.zoom=3;panel();draw();};
 if(q("texFile"))q("texFile").onchange=e=>{
  if(e.target.files[0])setTexture(e.target.files[0]);};
 if(q("bTexOn"))q("bTexOn").onclick=()=>{
  const c=q("cTex");c.checked=!c.checked;panel();draw();};
 if(q("poseFile"))q("poseFile").onchange=e=>{
  const f=e.target.files[0];if(!f)return;
  f.text().then(t=>{try{loadClip(t);panel();draw();}
   catch(err){alert("не читается: "+err.message);}});};
 if(q("clipFrame"))q("clipFrame").onchange=e=>{applyClipFrame(+e.target.value);draw();};
 if(q("bSheet"))q("bSheet").onclick=()=>{
  const cell=OPT.cell,px=OPT.scale||REF.px_per_unit;
  const poses=(OPT.allFrames&&CLIP)?clipPoses():[pose];
  busy("рисую "+(poses.length*8)+" кадров…");
  setTimeout(()=>{
   const r=renderSprites(cell,px,q("cTex").checked,poses);
   const p=q("prev");p.innerHTML="";
   const im=r.canvas;im.style.width="100%";im.style.imageRendering="pixelated";
   im.style.background="#111";p.appendChild(im);
   downloadSheet();busy("");},30);};
}
panel();draw();
window.__studio=()=>({STATS,bones:NAMES.length,skin:!!SKIN,step:STEP});
</script></body></html>
"""

ref = open(REFP, encoding="utf-8").read()
LIBP = os.path.join(ROOT, "tools", "webanim", "poselib.json")
lib = open(LIBP, encoding="utf-8").read() if os.path.exists(LIBP) else '{"bones":[],"poses":{}}'
out = HTML.replace("__REFPAYLOAD__", ref).replace("__POSELIB__", lib)
open(DEST, "w", encoding="utf-8").write(out)

# Проверка синтаксиса каждого блока: одна опечатка роняет весь блок целиком,
# а в браузере это выглядит как «функция не определена» без внятной причины.
import re, shutil, subprocess, tempfile
node = shutil.which("node")
if node:
    bad = 0
    for i, m in enumerate(re.finditer(r"(?s)<script>(.*?)</script>", out), 1):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(m.group(1))
            tmp = f.name
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        os.unlink(tmp)
        if r.returncode:
            bad += 1
            print("!! блок %d не разбирается:" % i)
            print("\n".join(r.stderr.strip().splitlines()[:6]))
    if not bad:
        print("синтаксис всех блоков в порядке")
else:
    print("node не найден — проверка синтаксиса пропущена")

print("записано %s  %.2f MB" % (DEST, os.path.getsize(DEST) / 1024 / 1024))
