from game_engine.source_falsification import _timer_counter_cycles, analyze_source


def run60_spec():
    return {
        "interaction_invariant": (
            "Safe passages without impact increase a tension counter; after ten seconds of safety, "
            "new hazards spawn and the safe orbital band narrows."
        ),
        "player_goal": "Maintain orbit as long as possible.",
        "core_loop": ["Accumulate safe-pass seconds.", "When tension peaks, new hazards spawn."],
        "prototype_scope": ["Target a 30-60 second representative run with immediate restart."],
        "timing_contract": {
            "simulation": "fixed-step 60 Hz accumulator",
            "max_frame_dt_seconds": 0.05,
            "deterministic_seed": True,
        },
        "telemetry_contract": {"snapshot": ["score"], "events": ["action_accepted"]},
    }


RUN60_ORBITING_AURORA = r"""
<script>
const sim={dt:1/60,maxDt:.05,t:0,acc:0,playing:true,tension:0,tensionTime:0,
  star:{r:20},hazards:[],lastAction:0};
function reset(){sim.playing=true;sim.tension=0;sim.tensionTime=0;sim.hazards=[]}
function spawnHazard(){
 const angle=Math.random()*Math.PI*2;
 sim.hazards.push({vx:-Math.sin(angle)*0.5,vy:Math.cos(angle)*0.5,radius:12,life:200});
}
function update(delta){
 for(let h of sim.hazards){h.x+=h.vx*delta;h.y+=h.vy*delta;h.life--}
 sim.tensionTime+=delta;
 if(sim.tensionTime>=10){
   sim.tension=Math.min(10,sim.tension+1);sim.tensionTime=0;
   if(sim.tension>=10){sim.tension=0;spawnHazard()}
 }
 if(delta>sim.maxDt)delta=sim.maxDt;
}
function loop(timestamp){
 if(!sim.lastTimestamp)sim.lastTimestamp=timestamp;
 const delta=(timestamp-sim.lastTimestamp)/1000;
 sim.lastTimestamp=timestamp;sim.acc+=delta;
 while(sim.acc>=sim.dt){update(sim.dt);sim.acc-=sim.dt}
 if(sim.playing)requestAnimationFrame(loop);
}
canvas.addEventListener('click',()=>{if(!sim.playing)reset()});
</script>
"""


def test_run60_orbiting_aurora_is_falsified_without_model_judgment():
    report = analyze_source(RUN60_ORBITING_AURORA, run60_spec())
    codes = {row["code"] for row in report["findings"]}
    assert report["qualified"] is False
    assert {
        "nondeterministic_rng",
        "missing_telemetry_contract",
        "uncapped_accumulator_dt",
        "restart_loop_not_resumed",
        "escalation_after_representative_run",
        "hazard_travel_below_own_radius",
    }.issubset(codes)


def test_nested_timer_counter_arithmetic_exposes_100_second_escalation():
    cycles = _timer_counter_cycles(RUN60_ORBITING_AURORA)
    assert cycles
    assert cycles[0]["timer"] == "sim.tensionTime"
    assert cycles[0]["counter"] == "sim.tension"
    assert cycles[0]["estimated_seconds"] == 100.0


def test_clean_source_can_reach_human_or_llm_judgment():
    source = r"""
    <script>
    const sim={acc:0,dt:1/60,playing:true};
    let seed=7;function rng(){seed=(seed*1664525+1013904223)>>>0;return seed/4294967296}
    window.__GAME_ENGINE_TELEMETRY__={schema_version:'0.1',snapshot:()=>({score:0}),events:()=>[]};
    function reset(){sim.playing=true;requestAnimationFrame(loop)}
    function update(dt){void dt;void rng()}
    function loop(t){const delta=Math.min(.05,(t-(sim.last||t))/1000);sim.last=t;sim.acc+=delta;
      while(sim.acc>=sim.dt){update(sim.dt);sim.acc-=sim.dt}if(sim.playing)requestAnimationFrame(loop)}
    canvas.addEventListener('click',()=>{if(!sim.playing)reset()});
    </script>
    """
    report = analyze_source(source, run60_spec())
    assert report["qualified"] is True
    assert report["blockers"] == 0
