#version 450 core

out vec4 out_fragColor;

in vec2 texCoord;
flat in float layer;

uniform sampler2DArray texArray;
uniform float u_shadowAlpha;

void main() {
    float a = texture(texArray, vec3(texCoord, layer)).a;
    if (a < 0.001) discard;
    out_fragColor = vec4(0.0, 0.0, 0.0, a * u_shadowAlpha);
}

