function tests = test_identification
tests = functiontests(localfunctions);
end

function testResult(testCase)
s = load(fullfile(fileparts(mfilename('fullpath')), 'result.mat'));
verifyGreaterThan(testCase, s.result.fit_percent, 70);
end
