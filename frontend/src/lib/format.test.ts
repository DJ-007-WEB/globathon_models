import { describe, expect, it } from "vitest";
import { formatKwh, formatNumber, formatSigned, formatInterval, statusTone } from "./format";

describe("format", () => {
  it("keeps null distinct from zero", () => {
    expect(formatKwh(null)).toBe("—");
    expect(formatKwh(undefined)).toBe("—");
    expect(formatKwh(0)).toBe("0 kWh");
    expect(formatNumber(Number.NaN)).toBe("—");
  });

  it("uses a true minus sign and never rounds a non-zero value to zero", () => {
    expect(formatNumber(-344.6)).toBe("−344.6");
    expect(formatNumber(0.004, 1)).toBe("<0.1");
    expect(formatNumber(-0.004, 1)).toBe("−<0.1");
    expect(formatSigned(13240.4)).toBe("+13,240.4");
  });

  it("formats sampling intervals", () => {
    expect(formatInterval(900)).toBe("15 min");
    expect(formatInterval(3600)).toBe("1 h");
    expect(formatInterval(null)).toBe("—");
  });

  it("maps statuses to tones", () => {
    expect(statusTone("partial")).toBe("warning");
    expect(statusTone("fail")).toBe("danger");
    expect(statusTone("success")).toBe("success");
  });
});
