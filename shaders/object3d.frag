#version 450 core

out vec4 out_fragColor;
in vec2 texCoord;
flat in float layer;
uniform sampler2DArray texArray;

void main() {
    out_fragColor = texture(texArray, vec3(texCoord, layer));
    if (out_fragColor.a < 0.001) discard;
    out_fragColor.rgb *= out_fragColor.a;
}
