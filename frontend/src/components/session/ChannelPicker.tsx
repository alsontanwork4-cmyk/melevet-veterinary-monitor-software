import { Channel } from "../../types/api";

interface ChannelPickerProps {
  channels: Channel[];
  selectedChannelIds: number[];
  onChange: (channelIds: number[]) => void;
}

export function ChannelPicker({ channels, selectedChannelIds, onChange }: ChannelPickerProps) {
  function toggle(channelId: number) {
    if (selectedChannelIds.includes(channelId)) {
      onChange(selectedChannelIds.filter((id) => id !== channelId));
    } else {
      onChange([...selectedChannelIds, channelId]);
    }
  }

  return (
    <div className="card compact-card">
      <h4>Signal Channels</h4>
      <div className="channel-list">
        {channels.map((channel) => (
          <label key={channel.id} className="checkbox-row">
            <input
              type="checkbox"
              checked={selectedChannelIds.includes(channel.id)}
              onChange={() => toggle(channel.id)}
            />
            {channel.name}
          </label>
        ))}
      </div>
    </div>
  );
}
