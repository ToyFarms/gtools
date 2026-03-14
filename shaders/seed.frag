#version 450 core

out vec4 out_fragColor;
in vec2 baseTexCoord;
in vec2 overlayTexCoord;
in vec3 baseTint;
in vec3 overlayTint;
flat in float layer;

uniform sampler2DArray u_texture;

void main() {
    vec4 baseColor = texture(u_texture, vec3(baseTexCoord, layer));
    vec4 overlayColor = texture(u_texture, vec3(overlayTexCoord, layer));

    vec4 base = vec4(baseTint * baseColor.rgb * baseColor.a, baseColor.a);
    vec4 overlay = vec4(overlayTint * overlayColor.rgb * overlayColor.a, overlayColor.a);

    out_fragColor = overlay + (1.0 - overlayColor.a) * base;
    if (out_fragColor.a < 0.01) discard;
}
