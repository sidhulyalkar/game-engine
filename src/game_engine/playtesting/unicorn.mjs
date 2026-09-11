// Trusted-source diagnostic adapter. node:vm is NOT a security sandbox.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const scenario = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = process.argv[2];
const files = ['core.js','herd.js','render.js','ui.js','top10.js','polish.js','whip.js','worlds.js','expansion.js'];
const handlers = new Map();
const on = (name, fn, capture) => {
  const list = handlers.get(name) || [];
  list.push({fn, capture: !!capture}); handlers.set(name, list);
};
const graphics = new Proxy({
  createLinearGradient: () => ({addColorStop(){}}),
  createRadialGradient: () => ({addColorStop(){}}),
  measureText: s => ({width: String(s).length * 8})
}, {get: (o, k) => k in o ? o[k] : () => {}});
const canvas = {width:1280,height:720,getContext:()=>graphics,
  getBoundingClientRect:()=>({left:0,top:0,width:1280,height:720}),
  addEventListener:(n,f,c)=>on('canvas:'+n,f,c)};
let wallTick = 0, randomState = scenario.seed;
const math = Object.create(Math);
math.random = () => { randomState = (Math.imul(1664525,randomState)+1013904223)>>>0; return randomState/4294967296; };
const epoch = 1700000000000;
class FixedDate extends Date {
  constructor(...args){super(...(args.length ? args : [FixedDate.now()]));}
  static now(){return epoch + wallTick * 1000/60;}
}
const audioNode = () => ({gain:{value:0,setValueAtTime(){},exponentialRampToValueAtTime(){}},
  frequency:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){},start(){},stop(){}});
class AudioContext {constructor(){this.currentTime=0;this.destination={};} createGain(){return audioNode();} createOscillator(){return audioNode();}}
const box = {Math:math,Date:FixedDate,Uint8Array,AudioContext,
  console:{log(){},warn(){},error(){}},localStorage:{},
  document:{getElementById:()=>canvas,createElement:()=>({getContext:()=>graphics})},
  addEventListener:on,requestAnimationFrame:()=>{},__seed:scenario.seed,__setup:scenario.setup};
vm.createContext(box, {codeGeneration:{strings:false,wasm:false}});
const evaluate = code => vm.runInContext(code, box, {timeout:2000});
evaluate(files.map(f=>fs.readFileSync(path.join(root,'src',f),'utf8')).join('\n'));
evaluate(`today=()=>__seed; zone=__setup.world; S.s('ccMode',__setup.difficulty); mode=__setup.difficulty;
  if(__setup.entry==='campaign') startLevel(1);
  else if(__setup.entry==='tutorial') startLevel(0);
  draw();`);

function fire(name, props={}) {
  // Dispatch in-context as well, so a broken handler is subject to vm timeout.
  box.__event = {code:'',repeat:false,button:0,clientX:0,clientY:0,
    preventDefault(){},stopImmediatePropagation(){this.stopped=true;},...props};
  for(const h of [...(handlers.get(name)||[])].sort((a,b)=>Number(b.capture)-Number(a.capture))){
    box.__handler = h.fn; evaluate('__handler(__event)');
    if(box.__event.stopped) break;
  }
}
const codes={left:'KeyA',right:'KeyD',up:'KeyW',down:'KeyS',start:'Enter',switch:'ShiftLeft',dash:'Space',pause:'Escape',rules:'KeyC'};
let held = new Set(), observations = [];
const snapshot = () => JSON.parse(evaluate(`JSON.stringify({
  tick:${wallTick},phase:state,world:zone,paused:!!paused,
  player:unis[caps[0]]?{x:unis[caps[0]].x,y:unis[caps[0]].y}:null,
  progress:level?structPct():intro.step/10,
  deaths:null,events:[],
  entities:unis.filter(u=>u.live).map(u=>({id:String(u.id),x:u.x,y:u.y,
    exempt:!!(u.distract||u.stun||cleaners.some(c=>c.u===u.id)),controlled:u===unis[caps[0]]})),
  metrics:{score,paint:paintPct(),captured:cleaners.filter(c=>c.u>=0).length,
    tutorial_step:intro.step,landmarks:LM.filter(lmDone).length,won:landWin>0}
})`));
observations.push(snapshot());
const changes=[];
for(const action of scenario.actions){
  if(action.pointer)fire('canvas:mousemove',{clientX:action.pointer[0]*1280,clientY:action.pointer[1]*720});
  const next=new Set(action.buttons);
  for(const b of held)if(!next.has(b))fire(b==='whip'?'canvas:mouseup':'keyup',{code:codes[b]||''});
  for(const b of next)if(!held.has(b))fire(b==='whip'?'canvas:mousedown':'keydown',{code:codes[b]||''});
  held=next;
  for(let i=0;i<action.ticks;i++){
    wallTick++; box.__time=wallTick*1000/60;
    evaluate('frame(__time)');
    const row=snapshot(), prev=observations[observations.length-1];
    // Capture transitions even between regular samples.
    if(row.phase!==prev.phase||row.metrics.tutorial_step!==prev.metrics.tutorial_step||row.metrics.captured!==prev.metrics.captured)
      changes.push({tick:wallTick,phase:row.phase,tutorial_step:row.metrics.tutorial_step,captured:row.metrics.captured});
    if(wallTick%6===0||i===action.ticks-1){row.events=changes.splice(0);observations.push(row);}
  }
}
process.stdout.write(JSON.stringify({adapter:'unicorn-v1',tick_hz:60,evidence_kind:'instrumented-source',observations}));
