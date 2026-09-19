"""Use a server tokenizer where available; never label a byte bound as tokens."""
import json


def input_limit(client):
    return 32 * 1024 if getattr(client, 'budget_kind', 'tokens') == 'serialized_bytes' else 6144


def measure_input(client, messages):
    if getattr(client, 'budget_kind', 'tokens') == 'serialized_bytes':
        return len(json.dumps({'messages': messages, 'schema': getattr(client, 'output_schema', None)},
                              ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    return client.count_prompt_tokens(messages)


def reported_input_tokens(client, completion, measured):
    if completion.input_tokens is not None:
        return completion.input_tokens
    return measured if getattr(client, 'budget_kind', 'tokens') == 'tokens' else None
