#version 450 core

out vec4 out_fragColor;
in vec2 texCoord;
flat in float texLayer;
flat in float paintIndex;
flat in uint tint;
flat in float opacity;

uniform sampler2DArray texArray;

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


vec4 unpackColor(uint c) {
    return vec4(
        float((c >> 24) & 0xFFu) / 255.0,  // R
        float((c >> 16) & 0xFFu) / 255.0,  // G
        float((c >>  8) & 0xFFu) / 255.0,  // B
        float((c >>  0) & 0xFFu) / 255.0   // A
    );
}

void main() {
    vec4 base = texture(texArray, vec3(texCoord, texLayer));
    base.a *= opacity;
    // premultiplied output; a black tint (a == 0) renders the alpha silhouette
    // as the drop shadow
    base.rgb *= unpackColor(tint).rgb * COLOR_TABLE[int(paintIndex)] * base.a;
    if (base.a < 0.001) discard;
    out_fragColor = base;
}
