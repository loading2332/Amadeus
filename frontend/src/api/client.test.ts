import axios, { AxiosError, CanceledError } from "axios";

import { ApiError, createApi, installAuthRecovery, toApiError } from "./client";

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

  it("refreshes and replays a safe read exactly once after a 401", async () => {
    const instance = axios.create();
    const recover = vi.fn().mockResolvedValue(undefined);
    let attempts = 0;
    instance.defaults.adapter = (config) => {
      attempts += 1;
      if (attempts === 1) {
        return Promise.reject(
          new AxiosError("expired", "ERR_BAD_RESPONSE", config, undefined, {
            data: { detail: "expired" },
            status: 401,
            statusText: "Unauthorized",
            headers: {},
            config,
          }),
        );
      }
      return Promise.resolve({
        data: { ok: true },
        status: 200,
        statusText: "OK",
        headers: {},
        config,
      });
    };
    installAuthRecovery(instance, recover);

    await expect(instance.get("/safe")).resolves.toMatchObject({ data: { ok: true } });
    expect(recover).toHaveBeenCalledOnce();
    expect(attempts).toBe(2);
  });

  it("does not automatically replay a non-idempotent write after a 401", async () => {
    const instance = axios.create();
    const recover = vi.fn().mockResolvedValue(undefined);
    instance.defaults.adapter = (config) =>
      Promise.reject(
        new AxiosError("expired", "ERR_BAD_RESPONSE", config, undefined, {
          data: { detail: "expired" },
          status: 401,
          statusText: "Unauthorized",
          headers: {},
          config,
        }),
      );
    installAuthRecovery(instance, recover);

    await expect(instance.post("/unsafe", {})).rejects.toMatchObject({ status: 401 });
    expect(recover).not.toHaveBeenCalled();
  });
});
