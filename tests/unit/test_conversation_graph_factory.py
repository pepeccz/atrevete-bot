from unittest.mock import patch


def test_create_conversation_graph_delegates_to_create_graph():
    from agent.graphs.conversation_flow import create_conversation_graph

    sentinel = object()

    with patch("agent.graphs.conversation_flow.create_graph", return_value=sentinel) as mock_create:
        result = create_conversation_graph(checkpointer="checkpoint")

    assert result is sentinel
    mock_create.assert_called_once_with(checkpointer="checkpoint")
