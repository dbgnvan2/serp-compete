import pytest
from unittest.mock import MagicMock, patch
from src.main import pre_flight_check

@patch('src.main.DataForSEOClient')
@patch('src.main.ReframeEngine')
@patch('src.main.GSCManager')
@patch('src.main.load_shared_config')
@patch('requests.get')
def test_pre_flight_check_low_balance(mock_get, mock_config, mock_gsc, mock_reframe, mock_dfs):
    # Mock config to have secrets path
    mock_config.return_value = {"auth": {"gsc_client_secrets": "dummy.json"}}
    with patch('os.path.exists', return_value=True):
        # Mock low balance response
        mock_get.return_value.json.return_value = {
            'tasks': [{'result': [{'money': {'balance': -0.01}}]}]
        }
        
        with patch.dict('os.environ', {
            'DATAFORSEO_LOGIN': 'test', 'DATAFORSEO_PASSWORD': 'test',
            'OPENAI_API_KEY': 'test', 'MOZ_TOKEN': 'test'
        }):
            assert pre_flight_check() is None

@patch('src.main.DataForSEOClient')
@patch('src.main.ReframeEngine')
@patch('src.main.GSCManager')
@patch('src.main.load_shared_config')
@patch('requests.get')
def test_pre_flight_check_success(mock_get, mock_config, mock_gsc, mock_reframe, mock_dfs):
    # Mock config
    mock_config.return_value = {"auth": {"gsc_client_secrets": "dummy.json"}}
    with patch('os.path.exists', return_value=True):
        # Mock positive balance
        mock_get.return_value.json.return_value = {
            'tasks': [{'result': [{'money': {'balance': 10.0}}]}]
        }
        # Mock OpenAI model retrieval success
        mock_reframe_instance = MagicMock()
        mock_reframe.return_value = mock_reframe_instance
        
        # Mock GSC Success
        mock_gsc_instance = MagicMock()
        mock_gsc.return_value = mock_gsc_instance
        mock_gsc_instance.test_connection.return_value = (True, "Success")
        
        with patch.dict('os.environ', {
            'DATAFORSEO_LOGIN': 'test', 'DATAFORSEO_PASSWORD': 'test',
            'OPENAI_API_KEY': 'test', 'MOZ_TOKEN': 'test'
        }):
            assert pre_flight_check() is not None
