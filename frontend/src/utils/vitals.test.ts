import { describe, expect, it } from "vitest";

import { friendlyChannelName, isKeyVitalChannel } from "./vitals";

describe("vitals core labeling", () => {
  it("does not classify respiratory rate as a key vital", () => {
    expect(isKeyVitalChannel("resp_rate_be_u16")).toBe(false);
    expect(isKeyVitalChannel("respiratory_rate")).toBe(false);
  });

  it("keeps NIBP labels under NIBP (Blood Pressure) naming", () => {
    expect(friendlyChannelName("nibp_systolic_raw")).toBe("NIBP (Blood Pressure) Systolic");
    expect(friendlyChannelName("nibp_map_raw")).toBe("NIBP (Blood Pressure) MAP");
    expect(friendlyChannelName("nibp_diastolic_raw")).toBe("NIBP (Blood Pressure) Diastolic");
  });
});
