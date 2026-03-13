#version 450 core
in vec2 v_tex;
out vec4 f_color;

uniform sampler2D u_texture;
uniform vec3 u_textColor;

void main() {
    float alpha = texture(u_texture, v_tex).r;
    if (alpha < 0.01) discard;
    f_color = vec4(u_textColor * alpha, alpha);
}
