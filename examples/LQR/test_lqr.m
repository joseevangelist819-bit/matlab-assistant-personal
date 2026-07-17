function tests = test_lqr
tests = functiontests(localfunctions);
end

function testResult(testCase)
s = load(fullfile(fileparts(mfilename('fullpath')), 'result.mat'));
verifyTrue(testCase, s.result.controllable);
verifyTrue(testCase, s.result.stable);
verifyLessThan(testCase, s.result.final_state_norm, 1e-3);
end
