function tests = test_kalman
tests = functiontests(localfunctions);
end

function testResult(testCase)
s = load(fullfile(fileparts(mfilename('fullpath')), 'result.mat'));
verifyTrue(testCase, s.result.improved);
verifyLessThan(testCase, s.result.estimate_rmse, s.result.measurement_rmse);
end
