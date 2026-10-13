#version 330 core
in vec2 TexCoord;
out vec4 FragColor;

uniform sampler2D inputTexture;
uniform bool firstPass;
uniform float percentile; // 0.95 для 95-го процентиля

// Размер гистограммы (можно настроить)
const int HISTOGRAM_SIZE = 256;

void main()
{
    if (firstPass) {
        // Первый проход: собираем статистику
        vec4 texColor = texture(inputTexture, TexCoord);
        float raw = texColor.r;
        if (isnan(raw)) {
            FragColor = vec4(-1.0, raw, 0.0, 0.0);
            return;
        }
        float volume = abs(raw); // Берем абсолютное значение объема
        float bin = floor(volume * (HISTOGRAM_SIZE - 1));
        FragColor = vec4(bin, volume, 1.0, 1.0);
    } else {
        // Второй проход: вычисляем процентиль
        vec4 texColor = texture(inputTexture, TexCoord);
        float bin = texColor.r; // Номер бина из первого прохода
        float value = texColor.g; // Значение объема из первого прохода

        if (isnan(value) || bin < 0.0) {
            FragColor = vec4(0.0, 0.0, 0.0, 1.0);
            return;
        }
        
        // Нормализуем номер бина к диапазону [0, 1]
        float normalizedBin = bin / float(HISTOGRAM_SIZE - 1);
        
        // Если нормализованный номер бина больше или равен процентилю, возвращаем значение
        if (normalizedBin >= percentile) {
            FragColor = vec4(value, 0.0, 0.0, 1.0);
        } else {
            FragColor = vec4(0.0, 0.0, 0.0, 1.0);
        }
    }
} 
