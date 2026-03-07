import { useMemo } from "react";

import { Channel } from "../../types/api";
import { channelDisplayLabel, isKeyVitalChannel, keyVitalPriority } from "../../utils/vitals";

interface VitalSelectorProps {
  channels: Channel[];
  selectedChannelIds: number[];
  onChange: (channelIds: number[]) => void;
}

function channelSort(a: Channel, b: Channel): number {
  const priorityDelta = keyVitalPriority(a.name) - keyVitalPriority(b.name);
  if (priorityDelta !== 0) {
    return priorityDelta;
  }

  const validDelta = b.valid_count - a.valid_count;
  if (validDelta !== 0) {
    return validDelta;
  }

  return a.channel_index - b.channel_index;
}

export function VitalSelector({ channels, selectedChannelIds, onChange }: VitalSelectorProps) {
  const sortedChannels = useMemo(() => [...channels].sort(channelSort), [channels]);
  const vitalChannels = useMemo(
    () => sortedChannels.filter((channel) => isKeyVitalChannel(channel.name)),
    [sortedChannels]
  );

  function toggle(channelId: number) {
    if (selectedChannelIds.includes(channelId)) {
      onChange(selectedChannelIds.filter((id) => id !== channelId));
      return;
    }
    onChange([...selectedChannelIds, channelId]);
  }

  return (
    <div className="card compact-card stack-md">
      <div className="stack-md">
        <h4>Vitals to Display</h4>
        <p className="helper-text">
          Start with core vitals. Open advanced selection only if you need technical channels.
        </p>
      </div>

      {vitalChannels.length > 0 ? (
        <div className="chips">
          {vitalChannels.map((channel) => (
            <button
              key={channel.id}
              type="button"
              className={selectedChannelIds.includes(channel.id) ? "chip chip-active" : "chip"}
              onClick={() => toggle(channel.id)}
            >
              {channelDisplayLabel(channel.name, channel.unit)}
            </button>
          ))}
        </div>
      ) : (
        <div className="helper-text">
          No standard vital channels were detected automatically. Use advanced selection below.
        </div>
      )}

      <details className="advanced-details">
        <summary>Advanced channel selection</summary>
        <div className="channel-list">
          {sortedChannels.map((channel) => (
            <label key={channel.id} className="checkbox-row">
              <input
                type="checkbox"
                checked={selectedChannelIds.includes(channel.id)}
                onChange={() => toggle(channel.id)}
              />
              <span>
                {channelDisplayLabel(channel.name, channel.unit)}
                <span className="channel-code">{channel.name}</span>
              </span>
            </label>
          ))}
        </div>
      </details>
    </div>
  );
}
