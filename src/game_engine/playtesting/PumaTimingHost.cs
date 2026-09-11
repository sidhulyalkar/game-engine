using System;
using System.Collections.Generic;
using System.Text.Json;
using Wildbound.Core;

// A motor calibration fixture: ground contact is imposed, not simulated.
// Calls the original PumaMotor.Prepare; no copied movement equations.
internal static class PumaTimingHost
{
    static int Main()
    {
        try
        {
            using var doc = JsonDocument.Parse(Console.In.ReadToEnd());
            var plan = doc.RootElement;
            float dt = 1f / plan.GetProperty("tick_hz").GetInt32();
            var trials = new List<object>();
            foreach (var trial in plan.GetProperty("schedule").EnumerateArray())
            {
                string mechanism = trial.GetProperty("mechanism").GetString();
                string arm = trial.GetProperty("arm").GetString();
                int delay = trial.GetProperty("delay_ticks").GetInt32();
                var tuning = new MovementTuning();
                if (arm == "narrow")
                {
                    if (mechanism == "coyote") tuning.CoyoteSeconds = dt / 2;
                    else tuning.BufferSeconds = dt / 2;
                }
                var motor = new PumaMotor(new V2(), tuning);
                var steps = new List<object>();
                void Step(bool grounded, bool pressed)
                {
                    motor.Grounded = grounded;
                    var events = motor.Prepare(new PlayerInput { JumpPressed = pressed, JumpHeld = true }, dt);
                    steps.Add(new { grounded_before = grounded, jump_pressed = pressed,
                        events = (int)events, velocity_y = motor.Velocity.Y });
                }
                if (delay == 0) Step(true, true);
                else if (mechanism == "coyote")
                {
                    Step(true, false); // Establish the motor's internal coyote timer.
                    for (int i = 1; i <= delay; i++) Step(false, i == delay);
                }
                else
                {
                    Step(false, true); // Press before the imposed landing.
                    for (int i = 1; i <= delay; i++) Step(i == delay, false);
                }
                trials.Add(new { id = trial.GetProperty("id").GetString(),
                    coyote_seconds = tuning.CoyoteSeconds, buffer_seconds = tuning.BufferSeconds,
                    steps });
            }
            Console.Write(JsonSerializer.Serialize(new { scope = "imposed_contact_motor_calibration", trials }));
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.ToString()); return 2; }
    }
}
