#version 400 core

in vec2 TexCoord;

out vec4 FragColor;

uniform sampler2D volumeTexture;
uniform sampler2D colorTexture;
uniform float minValue;
uniform float maxValue;
uniform float powBase;
uniform bool usePowerScale;

uniform ivec2 u_resolution;
uniform int colorStep;
uniform float upperCutOff;
uniform float lowerCutOff;
uniform float fixedMaxVolume;
uniform float fixedMinVolume;
uniform bool splitMode;
uniform bool displayLevelSplitter;
uniform float avgVolume;
uniform vec4 maxVolumeFilterColor;
uniform float maxVolumeFilterValue;
uniform bool transparencyMode;

float reduceNormalizedValue(float x, int levelsCount) {
    float levelSize = 1.0 / float(levelsCount);
    return levelSize * floor(x * float(levelsCount) + 0.5);
}

vec4 getColor(float volume)
{
    bool isAsk = volume < 0;
    volume = abs(volume);

    if (maxVolumeFilterValue > 0.0 && volume > maxVolumeFilterValue)
    {
        return maxVolumeFilterColor;
    }

    float range = maxValue - minValue;
    float minVolume = minValue + range * lowerCutOff;
    float maxVolume = maxValue - range * upperCutOff;

    if (fixedMaxVolume != 0.0)
        maxVolume = fixedMaxVolume;
    if (fixedMinVolume != 0.0)
        minVolume = fixedMinVolume;

    // A fixed max can end up below the dynamic min (e.g. all visible levels above it),
    // which makes (maxVolume - minVolume) zero/negative and inverts the whole color
    // scale. Keep min just below max so the scale never inverts; in the normal case
    // (minVolume < maxVolume) this is a no-op and the look is unchanged.
    minVolume = min(minVolume, maxVolume - 1e-6);

    float normalizedLogVolume = 0.0;

    if (usePowerScale) {
        float powerMinVolume = pow(minVolume, powBase);
        float powerMaxVolume = pow(maxVolume, powBase);
        float powerVolume = pow(volume, powBase);

        normalizedLogVolume = (powerVolume - powerMinVolume) / (powerMaxVolume - powerMinVolume);
    }

    float normalizedVolume = usePowerScale ? normalizedLogVolume : (volume - minVolume) / (maxVolume - minVolume);
    
    normalizedVolume = clamp(normalizedVolume, 0.0, 1.0);

    if (colorStep > 0)
    {
        normalizedVolume = reduceNormalizedValue(normalizedVolume, colorStep);
    }

    float alpha = normalizedVolume * normalizedVolume;

    if (splitMode)
    {
        float halfValue = normalizedVolume / 2.0f;

        normalizedVolume = 0.5f + (isAsk?(-halfValue):halfValue);
    }

    vec4 color = texture(colorTexture, vec2(normalizedVolume, 0.5));

    if (transparencyMode)
    {
        color = vec4(color.rgb, alpha);
    }

    return color;
}

void main()
{
    vec2 texSize = textureSize(volumeTexture, 0);
    
    float texY = TexCoord.y;
    float level = floor(texY * texSize.y);
    float pixelSizeTx = 1.0 / (u_resolution.y); 
    float nextLevel = floor((texY + pixelSizeTx) * texSize.y);
    
    float alpha = 1.0f;
    
    if (displayLevelSplitter && level != nextLevel)
    {
        alpha = 0.5f;

        float volume1 = texture(volumeTexture, TexCoord).r;
        float volume2 = texture(volumeTexture, vec2(TexCoord.x, TexCoord.y + pixelSizeTx)).r;

        bool valid1 = !isnan(volume1);
        bool valid2 = !isnan(volume2);

        vec4 color1 = valid1 ? getColor(volume1) : vec4(0.0);
        vec4 color2 = valid2 ? getColor(volume2) : vec4(0.0);

        if (!valid1 && !valid2)
        {
            FragColor = vec4(0,0,0,0);
        }
        else if (!valid1)
        {
            FragColor = vec4(color2.rgb, 0.5);
        }
        else if (!valid2)
        {
            FragColor = vec4(color1.rgb, 0.5);
        }
        else
        {
            FragColor = vec4(mix(color1.rgb, color2.rgb, 0.5), alpha);
        }
    }
    else
    {
        float volume = texture(volumeTexture, TexCoord).r;

        if (!isnan(volume))
        {
            FragColor = getColor(volume);
        }
        else
            FragColor = vec4(0.0,0.0,0.0,0.0);
    }
}
