import { AxiosError, CanceledError } from "axios";

import { ApiError, createApi, toApiError } from "./client";

describe("API client", () => {
  it("routes semantic calls through the injected Axios boundary", async () => {
    const get = vi.fn().mockResolvedValue({ data: { owner_user_id: 3 } });
    const instance = { get } as never;
    await expect(createApi(instance).getBootstrap()).resolves.toEqual({ ownerUserId: 3 });
    expect(get).toHaveBeenCalledWith("/bootstrap", { signal: undefined });
  });

  it("deletes a session through the injected Axios boundary without decoding a body", async () => {
    const del = vi.fn().mockResolvedValue({ data: "" });
    const instance = { delete: del } as never;
    await expect(createApi(instance).deleteSession(7)).resolves.toBeUndefined();
    expect(del).toHaveBeenCalledWith("/sessions/7", { signal: undefined });
  });

  it("converts a safe non-2xx payload without exposing unknown fields", () => {
    const error = new AxiosError("raw secret", "ERR_BAD_RESPONSE", undefined, undefined, {
      data: { code: "active_turn_exists", detail: "该会话已有正在处理的请求", debug: "secret" },
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: { headers: {} } as never,
    });
    expect(toApiError(error)).toMatchObject({
      message: "该会话已有正在处理的请求",
      code: "active_turn_exists",
      status: 409,
      retryable: false,
    });
  });

  it("distinguishes network, cancellation, generic HTTP, and unknown failures", () => {
    expect(toApiError(new AxiosError("socket"))).toMatchObject({ code: "network_error", retryable: true });
    expect(toApiError(new CanceledError())).toMatchObject({ code: "request_cancelled", retryable: false });
    const http = new AxiosError("raw", "ERR_BAD_RESPONSE", undefined, undefined, {
      data: { trace: "hidden" }, status: 503, statusText: "Down", headers: {}, config: { headers: {} } as never,
    });
    expect(toApiError(http)).toMatchObject({ code: "http_503", retryable: true });
    expect(toApiError(new Error("secret"))).toEqual(expect.any(ApiError));
    expect(toApiError(new Error("secret")).message).toBe("发生未知错误，请重试");
  });
});
