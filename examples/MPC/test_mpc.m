function tests = test_mpc
tests = functiontests(localfunctions);
end

function testResult(testCase)
s = load(fullfile(fileparts(mfilename('fullpath')), 'result.mat'));
verifyTrue(testCase, s.result.finite);
verifyLessThan(testCase, s.result.final_error, 0.1);
end
