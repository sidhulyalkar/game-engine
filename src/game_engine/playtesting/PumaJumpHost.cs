using System;
using System.Collections.Generic;
using System.Text.Json;
using Wildbound.Core;

internal static class PumaJumpHost
{
    static GameSession Create(float gap, bool narrow)
    {
        var g = new GameSession();
        g.World.Platforms.Clear(); g.World.Enemies.Clear(); g.World.Hazards.Clear();
        g.World.Pickups.Clear(); g.World.Checkpoints.Clear(); g.World.Signs.Clear();
        g.World.Places.Clear(); g.World.Blooms.Clear();
        g.World.Spawn = new V2(-2, 1); g.World.Exit = new V2(100, 1);
        g.World.Add(-10, 0, 10, 1, Surface.Stone);
        g.World.Add(gap, 0, 30, 1, Surface.Stone);
        g.Player.Reset(g.World.Spawn);
        if (narrow) g.Player.Tuning.CoyoteSeconds = GameSession.StepSeconds / 2;
        return g;
    }

    static List<object> Run(float gap, bool narrow, int press, int horizon, out int departure)
    {
        var g = Create(gap, narrow);
        var rows = new List<object>();
        bool hadGround = false; departure = -1;
        for (int tick = 1; tick <= horizon; tick++)
        {
            g.Step(new PlayerInput { Move = 1, JumpPressed = tick == press,
                JumpHeld = press >= 0 && tick >= press });
            if (hadGround && !g.Player.Grounded && departure < 0) departure = tick;
            hadGround |= g.Player.Grounded;
            rows.Add(new { tick, x = g.Player.Position.X, y = g.Player.Position.Y,
                grounded = g.Player.Grounded, ground_index = g.Player.GroundIndex,
                events = (int)g.Events, deaths = g.Deaths, jump_pressed = tick == press });
            if (g.Deaths > 0) break;
        }
        return rows;
    }

    static int Main()
    {
        try
        {
            using var doc = JsonDocument.Parse(Console.In.ReadToEnd());
            var plan = doc.RootElement;
            int horizon = plan.GetProperty("horizon_ticks").GetInt32();
            var reference = new List<object>();
            var departures = new Dictionary<int, int>();
            foreach (var width in plan.GetProperty("gap_widths").EnumerateArray())
            {
                int gap = width.GetInt32();
                var rows = Run(gap, false, -1, horizon, out int departure);
                if (departure < 2) throw new Exception("Reference did not leave the platform");
                departures[gap] = departure;
                reference.Add(new { gap, departure_tick = departure, rows });
            }
            var trials = new List<object>();
            foreach (var trial in plan.GetProperty("schedule").EnumerateArray())
            {
                int gap = trial.GetProperty("gap").GetInt32();
                int press = departures[gap] + trial.GetProperty("offset_ticks").GetInt32();
                bool narrow = trial.GetProperty("arm").GetString() == "narrow";
                var tuning = Create(gap, narrow).Player.Tuning;
                var rows = Run(gap, narrow, press, horizon, out int unused);
                trials.Add(new { id = trial.GetProperty("id").GetString(), press_tick = press,
                    coyote_seconds = tuning.CoyoteSeconds,
                    buffer_seconds = tuning.BufferSeconds, rows });
            }
            Console.Write(JsonSerializer.Serialize(new { scope = "authored_gap_game_session", reference, trials }));
            return 0;
        }
        catch (Exception e) { Console.Error.WriteLine(e.ToString()); return 2; }
    }
}
