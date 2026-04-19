#version 450 core

out vec4 out_fragColor;
in vec2 v_worldPos;

uniform float u_ticksPerBeat;
uniform int u_beatsPerBar;
uniform vec2 u_zoom;

void main() {
    vec2 pos = v_worldPos;

    float pitch = pos.y / 32.0;
    int pitchInt = 127 - int(floor(pitch));

    bool isBlackKey = false;
    int p = pitchInt % 12;
    if (p == 1 || p == 3 || p == 6 || p == 8 || p == 10) isBlackKey = true;

    vec3 color = isBlackKey ? vec3(0.12) : vec3(0.16);

    if (p == 0) color += vec3(0.01);

    float pitchLine = step(1.0 - fwidth(pitch), fract(pitch));
    color = mix(color, vec3(0.08), pitchLine);

    float ticks = pos.x;
    float beat = ticks / u_ticksPerBeat;
    float bar = beat / float(u_beatsPerBar);

    float dBeat = fwidth(beat);
    float dBar = fwidth(bar);

    float beatDist = abs(fract(beat + 0.5) - 0.5);
    float barDist = abs(fract(bar + 0.5) - 0.5);

    float beatLine = step(beatDist, dBeat);
    float barLine = step(barDist, dBar);

    color = mix(color, vec3(0.25), beatLine);
    color = mix(color, vec3(0.45), barLine);

    out_fragColor = vec4(color, 1.0);
}
