using System;
using System.Collections.Generic;
using System.Text.Json;
using Wildbound.Core;

// Compiled alongside the template's actual Core/*.cs; never a physics rewrite.
internal static class PumaHost
{
    static bool Down(HashSet<string> keys, string key) => keys.Contains(key);
    static bool Press(HashSet<string> keys, HashSet<string> old, string key) => Down(keys, key) && !Down(old, key);
    static int Main()
    {
        try
        {
            using var doc = JsonDocument.Parse(Console.In.ReadToEnd());
            var scenario = doc.RootElement;
            int biome = scenario.GetProperty("setup").GetProperty("world").GetInt32();
            var g = new GameSession(new JourneySave { Biome = biome, FurthestBiome = biome });
            var rows = new List<object>();
            var pending = new List<object>();
            int tick = 0;
            object Snapshot() => new {
                tick, phase = g.Save.Completed ? "complete" : "play", world = g.Save.Biome, paused = g.Paused,
                player = new { x = g.Player.Position.X, y = g.Player.Position.Y },
                progress = (g.Save.Biome + Math.Clamp(g.Player.Position.X / Math.Max(1, g.World.Exit.X), 0, 1)) / 3f,
                deaths = g.Deaths, events = pending.ToArray(),
                entities = new[] { new { id = "puma", x = g.Player.Position.X, y = g.Player.Position.Y,
                    exempt = g.Recovery > 0 || g.Player.Charging, controlled = true } },
                metrics = new { health = g.Combat.Health, motes = g.Motes, discoveries = g.DiscoveryCount,
                    waystones = g.WaystoneCount, in_trial = g.InTrial, grounded = g.Player.Grounded }
            };
            rows.Add(Snapshot());
            var held = new HashSet<string>();
            foreach (var action in scenario.GetProperty("actions").EnumerateArray())
            {
                var next = new HashSet<string>();
                foreach (var b in action.GetProperty("buttons").EnumerateArray()) next.Add(b.GetString());
                if (Press(next, held, "pause")) g.SetPaused(!g.Paused);
                int count = action.GetProperty("ticks").GetInt32();
                for (int i = 0; i < count; i++)
                {
                    bool edge = i == 0;
                    var input = new PlayerInput {
                        Move = (Down(next,"right") ? 1 : 0) - (Down(next,"left") ? 1 : 0),
                        AimY = (Down(next,"up") ? 1 : 0) - (Down(next,"down") ? 1 : 0),
                        JumpHeld = Down(next,"jump"), JumpPressed = edge && Press(next,held,"jump"),
                        PounceHeld = Down(next,"pounce"), PouncePressed = edge && Press(next,held,"pounce"),
                        PounceReleased = edge && Down(held,"pounce") && !Down(next,"pounce"),
                        AttackPressed = edge && Press(next,held,"attack"), DashPressed = edge && Press(next,held,"dash"),
                        RollPressed = edge && Press(next,held,"roll"), StalkHeld = Down(next,"stalk"),
                        InteractPressed = edge && Press(next,held,"interact")
                    };
                    g.Step(input); tick++;
                    if(g.Events != GameEvent.None) pending.Add(new { tick, name = g.Events.ToString() });
                    if(tick % 12 == 0 || i == count - 1) { rows.Add(Snapshot()); pending.Clear(); }
                }
                held = next;
            }
            Console.Write(JsonSerializer.Serialize(new { adapter = "puma-v1", tick_hz = 120,
                evidence_kind = "instrumented-core", observations = rows }));
            return 0;
        }
        catch(Exception error) { Console.Error.WriteLine(error.ToString()); return 2; }
    }
}
