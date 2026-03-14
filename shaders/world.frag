#version 450 core

out vec4 out_fragColor;
in vec2 texCoord;
flat in float layer;
flat in float paintIndex;
uniform sampler2DArray texArray;
uniform float u_opacity;

const vec3 COLOR_TABLE[8] = vec3[8](
    vec3(1.0,   1.0,   1.0  ),  // 0b000 none
    vec3(1.0,   0.235, 0.235),  // 0b001 red
    vec3(0.235, 1.0,   0.235),  // 0b010 green
    vec3(1.0,   1.0,   0.235),  // 0b011 yellow
    vec3(0.235, 0.235, 1.0  ),  // 0b100 blue
    vec3(1.0,   0.235, 1.0  ),  // 0b101 purple
    vec3(0.235, 1.0,   1.0  ),  // 0b110 aqua
    vec3(0.235, 0.235, 0.235)   // 0b111 charcoal
);

void main() {
    vec4 base = texture(texArray, vec3(texCoord, layer));
    base.a *= u_opacity;
    base.rgb *= COLOR_TABLE[int(paintIndex)] * base.a;
    out_fragColor = base;
}
