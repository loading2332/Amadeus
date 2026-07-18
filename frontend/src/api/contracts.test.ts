import { ContractError, decodeBootstrap, decodeTurn } from "./contracts";

const turn = {
  turn_id: "turn-1",
  user_id: 1,
  session_id: 2,
  content: "原始问题",
  status: "failed",
  answer: null,
  partial_answer: "部分回答",
  stream_version: 3,
  retry_of_turn_id: null,
  error_code: "runtime_error",
  error_message: "处理请求时发生错误，请重试",
  error_retryable: true,
  metadata: {},
  created_at: null,
  updated_at: null,
  started_at: null,
  finished_at: null,
};

describe("API contract decoders", () => {
  it("decodes the server-owned bootstrap identity", () => {
    expect(decodeBootstrap({ owner_user_id: 7 })).toEqual({ ownerUserId: 7 });
  });

  it("keeps only the safe structured turn error", () => {
    expect(decodeTurn(turn).error).toEqual({
      code: "runtime_error",
      message: "处理请求时发生错误，请重试",
      retryable: true,
    });
  });

  it("rejects malformed boundary data", () => {
    expect(() => decodeBootstrap({ owner_user_id: "1" })).toThrow(ContractError);
    expect(() => decodeTurn({ ...turn, status: "mystery" })).toThrow(ContractError);
  });
});
