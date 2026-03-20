#version 450 core
in vec2 v_tex;
out vec4 f_color;

uniform sampler2D u_texture;
uniform vec3 u_textColor;
uniform float u_sdfPxRange;
uniform float u_edgeSoftness;
uniform float u_weight;

void main() {
    float sdf = texture(u_texture, v_tex).r;
    float signedDistance = sdf - 0.5 - u_weight;
    vec2 unitRange = vec2(u_sdfPxRange) / vec2(textureSize(u_texture, 0));
    vec2 screenTexSize = vec2(1.0) / max(fwidth(v_tex), vec2(1e-6));
    float screenPxRange = max(0.5 * dot(unitRange, screenTexSize), 1.0);
    float alpha = smoothstep(-u_edgeSoftness, u_edgeSoftness, signedDistance * screenPxRange);
    if (alpha < 0.01) discard;
    f_color = vec4(u_textColor * alpha, alpha);
}
