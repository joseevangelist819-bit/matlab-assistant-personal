root=fileparts(mfilename('fullpath'));A=[0 1;-2 -3];B=[0;1];C=[1 0];D=0;Q=diag([10 1]);R=0.5;
controllable=rank(ctrb(A,B))==2;K=lqr(A,B,Q,R);poles=eig(A-B*K);sys=ss(A-B*K,zeros(2,1),C,D);[y,t,x]=initial(sys,[1;0],0:0.01:8);
result=struct('controllable',controllable,'K',K,'poles_real',real(poles),'poles_imag',imag(poles),'stable',all(real(poles)<0),'final_state_norm',norm(x(end,:)));
save(fullfile(root,'result.mat'),'result','t','y','x');figure('Visible','off');plot(t,x,'LineWidth',1.3);grid on;title('LQR States');exportgraphics(gcf,fullfile(root,'result.png'));close(gcf);
